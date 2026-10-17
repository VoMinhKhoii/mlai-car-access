"""Arrival Plan engine: filter Stop Points by Hard Checks, then rank by walk (Q2, Q5–Q7, Q12, D15–D19)."""
from __future__ import annotations

import heapq
import math
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import flags, parking_data
from .config import GOONG_API_KEY, PICKUP_DWELL_MIN, REVERSE_LIMIT_M, WALK_CAP_M, WALK_WADE_M
from .evidence import STORE_EVIDENCE, WidthRange, blocked_ways_today, width_ranges
from .flood import (FloodProfile, FloodRecord, alarm_label, depth_at, flood_profiles, flood_status, tide_level,
                    worst_over, request_cache, evaluation_times, STATUS_ORDER)
from .legality import ORDER as LEGAL_ORDER
from .legality import legality_for_lot, legality_on_street, junction_distance
from .osm import AreaGraph, build_graph, haversine, DRIVABLE, MOTORBIKE_ONLY
from .vehicles import VehicleProfile, get_profile, three_point_width, turn_in_width

VN_TZ = timezone(timedelta(hours=7))
WALK_SPEED = 1.2  # m/s
INF = float("inf")

_WR: dict = {}
_FP: dict = {}
_PAID_REVISION: dict = {}


def area(lat: float, lon: float):
    STORE_EVIDENCE.refresh_footprints()
    g = build_graph(lat, lon)
    revision = getattr(g, '_engine_revision', None)
    if revision is None:
        revision = hashlib.sha256(repr((sorted(g.nodes.items()),
            [(w.id,w.nodes,sorted(w.tags.items())) for w in g.ways.values()])).encode()).hexdigest()
        g._engine_revision = revision
    key = (g.source, revision, tuple(f["enabled"] for f in flags.describe()))
    prior = _PAID_REVISION.get(g.source)
    if prior != revision:
        parking_data._PAID.pop(g.source, None)
        if len(_PAID_REVISION) >= 16:
            old_source = next(iter(_PAID_REVISION))
            _PAID_REVISION.pop(old_source)
            parking_data._PAID.pop(old_source, None)
        _PAID_REVISION[g.source] = revision
    wkey = key + (STORE_EVIDENCE.version,)
    if wkey not in _WR:
        if len(_WR) >= 16:
            _WR.pop(next(iter(_WR)))
        _WR[wkey] = width_ranges(g)
    if key not in _FP:
        if len(_FP) >= 16:
            _FP.pop(next(iter(_FP)))
        _FP[key] = flood_profiles(g)
    return g, _WR[wkey], _FP[key]


def invalidate_evidence() -> None:
    _WR.clear()


def _access(tags, mode):
    keys = ('motorcar','motor_vehicle','vehicle','access') if mode=='car' else ('foot','access')
    return next((tags[k] for k in keys if k in tags),'yes')


def _car_way_allowed(w):
    if w.highway not in DRIVABLE or w.tags.get('area')=='yes' or _access(w.tags,'car') in ('private','no'):
        return False
    return not MOTORBIKE_ONLY.search(w.name) or w.tags.get('motorcar') in ('yes','destination')


def _car_adjacency(g):
    if hasattr(g,'_engine_car_adj'):
        return g._engine_car_adj
    adj={}
    for e in g.edges:
        w=g.ways[e.way_id]
        if not _car_way_allowed(w) or any(_access(g.node_tags.get(n,{}),'car') in ('private','no') for n in (e.u,e.v)):
            continue
        direction=w.oneway or (1 if w.tags.get('junction')=='roundabout' else 0)
        if direction>=0:
            adj.setdefault(e.u,[]).append((e.idx,e.v))
        if direction<=0:
            adj.setdefault(e.v,[]).append((e.idx,e.u))
    g._engine_car_adj=adj
    return adj


# ---- per-vehicle fit ----------------------------------------------------------

def fit_class(wr: WidthRange, p: VehicleProfile) -> str:
    if wr.review:
        return "unknown"
    if wr.lo >= p.fits_min:
        return "fits"
    if wr.lo >= p.tight_min:
        return "tight"
    if wr.hi < p.tight_min:
        return "no"
    return "unknown"


def compute_fit(g: AreaGraph, wrs: dict[int, WidthRange], p: VehicleProfile):
    fit, notes = {}, {}
    for wid, w in g.ways.items():
        fit[wid] = fit_class(wrs[wid], p) if _car_way_allowed(w) else "no"
        for limit_key in ('maxwidth:physical', 'maxwidth'):
            limit = w.tags.get(limit_key)
            if not limit or fit[wid] in ('no', 'blocked'):
                continue
            try:
                max_width = float(limit.removesuffix(' m'))
                if p.mirror_width > max_width:
                    fit[wid], notes[wid] = 'no', 'Xe vượt giới hạn bề rộng được ghi trên đường'
            except ValueError:
                fit[wid], notes[wid] = 'unknown', 'Chưa đọc được đơn vị giới hạn bề rộng'
        limits = [k for k in ('maxweight','maxaxleload','maxheight','maxlength') if k in w.tags]
        if limits and fit[wid] not in ('no','blocked'):
            fit[wid], notes[wid] = 'unknown', 'Chưa xác minh xe đáp ứng giới hạn: '+', '.join(limits)
    for wid, b in blocked_ways_today().items():
        if wid in fit:
            fit[wid] = "blocked"
            notes[wid] = f"Tạm thời bị chặn hôm nay: {b.get('reason', 'vật cản')} ({b.get('source', 'tài xế báo')})"
    return fit, notes


# ---- graph search ---------------------------------------------------------------

def _usable(fit: str, flood: str, strict: bool) -> bool:
    if fit in ("no", "blocked") or flood == "blocked":
        return False
    if strict and (fit == "unknown" or flood in ("risky", "unknown")):
        return False
    return True


def _cost(length: float, fit: str) -> float:
    return length * (1.3 if fit == "tight" else 1.15 if fit == "unknown" else 1.0)


def dijkstra(adj, sources: dict[int, float], edge_ok, edge_cost, limit=INF):
    dist = dict(sources)
    pred: dict[int, tuple[int, int]] = {}
    pq = [(d, n) for n, d in sources.items()]
    heapq.heapify(pq)
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, INF) or d > limit:
            continue
        for eidx, m in adj.get(n, ()):
            if not edge_ok(eidx):
                continue
            nd = d + edge_cost(eidx)
            if nd < dist.get(m, INF):
                dist[m] = nd
                pred[m] = (eidx, n)
                heapq.heappush(pq, (nd, m))
    return dist, pred


def _path_nodes(pred, node):
    out = [node]
    while node in pred:
        node = pred[node][1]
        out.append(node)
    return out  # node → source


def _coords(g: AreaGraph, nodes):
    return [[g.nodes[n][1], g.nodes[n][0]] for n in nodes]


def _interp(g: AreaGraph, u: int, v: int, s: float, length: float):
    (la, lo), (lb, lob) = g.nodes[u], g.nodes[v]
    f = 0 if length == 0 else s / length
    return la + (lb - la) * f, lo + (lob - lo) * f


def _project(g: AreaGraph, lat: float, lon: float, predicate):
    """Nearest point on an edge whose way satisfies predicate → (edge, offset from u, distance)."""
    best = (None, 0.0, INF)
    kx = math.cos(math.radians(lat)) * 111320
    ky = 110540
    for e in g.edges:
        if not predicate(g.ways[e.way_id]):
            continue
        (la, lo), (lb, lob) = g.nodes[e.u], g.nodes[e.v]
        ax, ay = (lo - lon) * kx, (la - lat) * ky
        bx, by = (lob - lon) * kx, (lb - lat) * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[2]:
            best = (e, t * e.length, d)
    return best


# Directed edge states preserve heading at every junction. A state is
# (node, incoming edge); immediate edge reversal is a separate manoeuvre.
class _DriveSearch:
    def __init__(self, g, wrs, fit, p, fl_arr, fl_dep, estimate_only=False):
        self.g, self.wrs, self.fit, self.p = g, wrs, fit, p
        self.fl_arr, self.fl_dep = fl_arr, fl_dep
        self.estimate_only = estimate_only
        self.adj = _car_adjacency(g)
        self.main = {n for w in g.ways.values() if w.kind == 'main' and _car_way_allowed(w) for n in w.nodes}
        self.incoming = {}
        for a, es in self.adj.items():
            for ei, b in es:
                self.incoming.setdefault(b, []).append(ei)
        self.turns = {}
        self.arr = {strict: self._search(False, strict) for strict in (True, False)}
        self.ext = {strict: self._search(True, strict) for strict in (True, False)}

    def edge_ok(self, ei, departure, strict):
        wid = self.g.edges[ei].way_id
        if self.estimate_only:
            value = _width_estimate(self.wrs[wid])
            if value is None or value < self.p.tight_min:
                return False
        fm = self.fl_dep if departure else self.fl_arr
        return _usable(self.fit.get(wid, 'unknown'), fm[wid][0], strict)

    def turn(self, incoming, node, outgoing):
        if incoming == -1:
            # A local handoff may align with the main road. It does not prove
            # an arbitrary turn from that road into an alley.
            return 'pass' if self.g.ways[self.g.edges[outgoing].way_id].kind == 'main' else 'unknown'
        key = incoming, node, outgoing
        if key not in self.turns:
            self.turns[key] = _junction_turn(self.g, self.wrs, self.p, incoming, node, outgoing)
        return self.turns[key]

    def _search(self, reverse, strict):
        g = self.g
        if reverse:
            sources = {}
            for n in self.main:
                for ei in self.incoming.get(n, ()):
                    if not self.edge_ok(ei, True, strict):
                        continue
                    already_main = g.ways[g.edges[ei].way_id].kind == 'main'
                    turns_onto_main = any(g.ways[g.edges[oj].way_id].kind == 'main' and
                        self.edge_ok(oj, True, strict) and self.turn(ei, n, oj) != 'no' and
                        (not strict or self.turn(ei, n, oj) == 'pass') for oj, _ in self.adj.get(n, ()))
                    if already_main or turns_onto_main:
                        sources[n, ei] = 0.0
        else:
            sources = {(n, -1): 0.0 for n in self.main}
            sources.update({(n, ei): 0.0 for n in self.main for ei in self.incoming.get(n, ())
                            if g.ways[g.edges[ei].way_id].kind == 'main' and self.edge_ok(ei, False, strict)})
        dist, pred, queue = dict(sources), {}, [(0.0, state) for state in sources]
        heapq.heapify(queue)
        while queue:
            cost, state = heapq.heappop(queue)
            if cost != dist.get(state):
                continue
            node, incoming = state
            if reverse:
                edge = g.edges[incoming]
                if not self.edge_ok(incoming, True, strict):
                    continue
                prev = edge.v if edge.u == node else edge.u
                steps = [((prev, ei), incoming, self.turn(ei, prev, incoming))
                         for ei in self.incoming.get(prev, ())]
            else:
                steps = [((n, ei), ei, self.turn(incoming, node, ei)) for ei, n in self.adj.get(node, ())]
            for target, ei, turn in steps:
                if turn == 'no' or (strict and turn != 'pass') or not self.edge_ok(ei, reverse, strict):
                    continue
                nd = cost + _cost(g.edges[ei].length, self.fit[g.edges[ei].way_id])
                if nd < dist.get(target, INF):
                    dist[target], pred[target] = nd, state
                    heapq.heappush(queue, (nd, target))
        return dist, pred

    def arrival_options(self, c):
        if c.kind == 'lot':
            for strict in (True, False):
                dist, pred = self.arr[strict]
                states = [s for s in dist if s[0] == c.entrance]
                if states:
                    state = min(states, key=dist.get)
                    nodes = self._nodes(pred, state)[::-1]
                    geom = _coords(self.g, nodes) + [[c.lon, c.lat]]
                    yield {'strict': False, 'meters': round(_geometry_length(geom)), 'geometry': geom,
                           'flood': None, 'connector_unverified': True,
                           '_segments': self._segments(pred, state)}
                    return
            return
        e = self.g.edges[c.edge_idx]
        for side, a, b, tail in [('u',e.u,e.v,c.offset),('v',e.v,e.u,e.length-c.offset)]:
            if (e.idx,b) not in self.adj.get(a, ()):
                continue
            for strict in (True, False):
                if not self.edge_ok(e.idx, False, strict):
                    continue
                dist, pred = self.arr[strict]
                states = [(a, ei) for ei in [-1] + self.incoming.get(a, [])]
                states = [s for s in states if s in dist and self.turn(s[1],a,e.idx) != 'no' and
                          (not strict or self.turn(s[1],a,e.idx) == 'pass')]
                if not states:
                    continue
                state = min(states, key=dist.get)
                geom = _coords(self.g, self._nodes(pred,state)[::-1]) + [[c.lon,c.lat]]
                yield {'strict': strict, 'side': side, 'meters': round(_geometry_length(geom)),
                       'geometry': geom, 'flood': None,
                       '_segments': self._segments(pred, state) + [(e.idx, tail)]}
                break

    @staticmethod
    def _nodes(pred, state):
        nodes = [state[0]]
        while state in pred:
            state = pred[state]
            nodes.append(state[0])
        return nodes

    def _segments(self, pred, state, departure=False):
        segments = []
        while state in pred:
            previous = pred[state]
            ei = previous[1] if departure else state[1]
            segments.append((ei, self.g.edges[ei].length))
            state = previous
        return segments

    def exit(self, c, route):
        if c.kind == 'lot':
            return {'mode':'unknown','strict':False,'reverse_m':0,'tight_exit':False,
                    'text':'Chưa xác minh đường nối vào bãi và diện tích quay đầu', 'geometry':[]}
        g = self.g
        e = g.edges[c.edge_idx]
        a,b = (e.u,e.v) if route['side']=='u' else (e.v,e.u)
        back = c.offset if a==e.u else e.length-c.offset
        for strict in (True,False):
            dist,pred = self.ext[strict]
            if not self.edge_ok(e.idx,True,strict):
                continue
            state = (b,e.idx)
            if (e.idx,b) in self.adj.get(a,()) and state in dist:
                geom = [[c.lon,c.lat]] + _coords(g,self._nodes(pred,state))
                return {'mode':'through','strict':strict,'reverse_m':0,'tight_exit':False,
                        'manoeuvre_status':'verified_model' if strict else 'unknown',
                        '_segments': [(e.idx, e.length-back)] + self._segments(pred, state, True),
                        'text':'Đi tiếp ra đường lớn' if strict else 'Có đường thông trên bản đồ; chưa xác minh đủ bề rộng, ngập hoặc thao tác rẽ',
                        'geometry':geom}
            # Backing/turning against a one-way direction is never authorized.
            if (e.idx,a) not in self.adj.get(b,()):
                continue
            if _turning_space(c,g,self.wrs,self.p):
                states = [(a,e.idx)] if (a,e.idx) in dist else []
                if states:
                    state=min(states,key=dist.get)
                    return {'mode':'turn_here','strict':strict,'reverse_m':0,'tight_exit':False,
                            'manoeuvre_status':'verified_model' if strict else 'unknown',
                            '_segments': [(e.idx, back)] + self._segments(pred, state, True),
                            'text':'Quay đầu trong hành lang đủ bề rộng và chiều dài theo mô hình',
                            'geometry':[[c.lon,c.lat]]+_coords(g,self._nodes(pred,state))}
        # A physical junction is evidence of a possible manoeuvre, not proof of a K-turn.
        # Search the actual bidirectional reverse path up to the unchanged 60 m limit.
        if (e.idx,a) in self.adj.get(b,()) and self.edge_ok(e.idx,True,False):
            queue=[(back,a,e.idx,[a])];seen={}
            while queue:
                rev,n,previous,path=heapq.heappop(queue)
                if rev>2*REVERSE_LIMIT_M or rev>=seen.get((n,previous),INF):
                    continue
                seen[n,previous]=rev
                arms={m for ei,m in self.adj.get(n,()) if self.edge_ok(ei,True,False)}
                if n in self.main or len(arms)>=3:
                    dist,pred=self.ext[False]
                    states=[(n,ei) for ei in self.incoming.get(n,()) if (n,ei) in dist and ei!=previous]
                    if states:
                        state=min(states,key=dist.get)
                        return {'mode':'unknown','strict':False,'reverse_m':round(rev),'tight_exit':rev>REVERSE_LIMIT_M,
                                'text':f'Lùi khoảng {rev:.0f} m tới nút giao; chưa xác minh đủ diện tích và thao tác quay đầu',
                                'geometry':[[c.lon,c.lat]]+_coords(g,path+self._nodes(pred,state)[1:])}
                for ei,m in self.adj.get(n,()):
                    if ei==previous or not self.edge_ok(ei,True,False):
                        continue
                    if (ei,n) not in self.adj.get(m,()):
                        continue
                    if self.turn(previous,n,ei)=='no':
                        continue
                    heapq.heappush(queue,(rev+g.edges[ei].length,m,ei,path+[m]))
        return {'mode':'none','strict':False,'text':'Không tìm thấy đường ra theo chiều được phép trong dữ liệu hiện có'}


def _geometry_length(geometry):
    return sum(haversine(a[1],a[0],b[1],b[0]) for a,b in zip(geometry,geometry[1:]))


def _junction_turn(g,wrs,p,incoming,node,outgoing):
    if incoming==outgoing:
        return 'no'
    ie,oe=g.edges[incoming],g.edges[outgoing]
    before=ie.v if ie.u==node else ie.u
    after=oe.v if oe.u==node else oe.u
    la,lo=g.nodes[node]
    ax=(lo-g.nodes[before][1])*math.cos(math.radians(la)); ay=la-g.nodes[before][0]
    bx=(g.nodes[after][1]-lo)*math.cos(math.radians(la)); by=g.nodes[after][0]-la
    denom=math.hypot(ax,ay)*math.hypot(bx,by)
    angle=math.degrees(math.acos(max(-1,min(1,(ax*bx+ay*by)/denom)))) if denom else 180
    if angle<=15:
        return 'pass'
    a,b=wrs[ie.way_id],wrs[oe.way_id]
    if a.review or b.review or min(a.lo,b.lo)<=0 or angle>90+1e-6:
        return 'unknown'
    # The one-arc model covers a right-angle turn. Smaller angles use the same
    # conservative envelope; sharper turns need surveyed swept-path evidence.
    need=turn_in_width(p.id, min(12.0,math.floor(a.lo*2)/2))
    return 'pass' if b.lo>=need else 'unknown'


def _turning_space(c,g,wrs,p):
    from .vehicles import three_point_envelope
    width,length=three_point_envelope(p.id)
    e=g.edges[c.edge_idx]
    if wrs[e.way_id].review or wrs[e.way_id].lo<width:
        return False
    # Sum collinear corridor space in both directions, independent of way IDs.
    total=0.0
    for node,tail in [(e.u,c.offset),(e.v,e.length-c.offset)]:
        available=tail;prev=e.idx;seen={prev}
        while available<length:
            options=[(ei,n) for ei,n in _car_adjacency(g).get(node,()) if ei not in seen and
                     wrs[g.edges[ei].way_id].lo>=width and not wrs[g.edges[ei].way_id].review and
                     (ei,node) in _car_adjacency(g).get(n,())]
            if len(options)!=1:
                break
            ei,n=options[0]
            if _junction_angle(g,prev,node,ei)>15:
                break
            available+=g.edges[ei].length;seen.add(ei);prev,node=ei,n
        total+=available
    return total>=length


def _junction_angle(g,incoming,node,outgoing):
    ie,oe=g.edges[incoming],g.edges[outgoing]
    a=ie.v if ie.u==node else ie.u;b=oe.v if oe.u==node else oe.u
    lat,lon=g.nodes[node];scale=math.cos(math.radians(lat))
    x,y=(lon-g.nodes[a][1])*scale,lat-g.nodes[a][0]
    xx,yy=(g.nodes[b][1]-lon)*scale,g.nodes[b][0]-lat
    den=math.hypot(x,y)*math.hypot(xx,yy)
    return math.degrees(math.acos(max(-1,min(1,(x*xx+y*yy)/den)))) if den else 180


def _foot_allowed(w):
    mode = w.tags.get('foot', w.tags.get('access', 'yes'))
    return w.walkable and mode not in ('no','private')


class _WalkSearch:
    """One virtual-position pedestrian route supplies every walk field and cap."""
    def __init__(self,g,lat,lon,cap):
        self.g,self.dest,self.cap=g,(lat,lon),cap
        self.edge,self.offset,_=_project(g,lat,lon,_foot_allowed)
        self.dist,self.pred={},{}
        if self.edge is None:
            return
        e=self.edge
        self.snap=_interp(g,e.u,e.v,self.offset,e.length)
        if any(_access(g.node_tags.get(n,{}),'foot') in ('private','no') and
               haversine(*g.nodes[n],*self.snap)<.1 for n in (e.u,e.v)):
            self.edge=None
            return
        connector=haversine(*self.snap,lat,lon)
        src={e.u:connector+haversine(*g.nodes[e.u],*self.snap),
             e.v:connector+haversine(*g.nodes[e.v],*self.snap)}
        src={n:d for n,d in src.items() if _access(g.node_tags.get(n,{}),'foot') not in ('private','no')}
        self.dist,self.pred=dijkstra(g.walk_adj,src,
            lambda ei:_foot_allowed(g.ways[g.edges[ei].way_id]) and
            all(g.node_tags.get(n,{}).get('foot',g.node_tags.get(n,{}).get('access','yes')) not in ('private','no')
                for n in (g.edges[ei].u,g.edges[ei].v)),lambda ei:g.edges[ei].length,limit=cap)

    def path(self,c):
        if self.edge is None:
            return None
        g=self.g
        if c.kind=='lot':
            ce,off,_=_project(g,c.lat,c.lon,_foot_allowed)
            if ce is None:
                return None
            start=_interp(g,ce.u,ce.v,off,ce.length)
        else:
            ce,off=g.edges[c.edge_idx],c.offset
            if not _foot_allowed(g.ways[ce.way_id]):
                return None
            start=(c.lat,c.lon)
        prefix=[[c.lon,c.lat],[start[1],start[0]]]
        if any(_access(g.node_tags.get(n,{}),'foot') in ('private','no') and
               haversine(*g.nodes[n],*start)<.1 for n in (ce.u,ce.v)):
            return None
        options=[]
        if ce.idx==self.edge.idx:
            options.append((prefix+[[self.snap[1],self.snap[0]],[self.dest[1],self.dest[0]]],
                            [ce.idx] if abs(off-self.offset)>1e-6 else []))
        for node in (ce.u,ce.v):
            if node not in self.dist or _access(g.node_tags.get(node,{}),'foot') in ('private','no'):
                continue
            nodes=_path_nodes(self.pred,node)
            edges=([ce.idx] if haversine(*start,*g.nodes[node])>1e-6 else [])
            edges += [self.pred[n][0] for n in nodes if n in self.pred]
            if haversine(*g.nodes[nodes[-1]],*self.snap)>1e-6:
                edges.append(self.edge.idx)
            options.append((prefix+_coords(g,nodes)+[[self.snap[1],self.snap[0]],[self.dest[1],self.dest[0]]],edges))
        if not options:
            return None
        geom,edges=min(options,key=lambda option:_geometry_length(option[0]))
        # Remove identical points, leaving all actual connectors in the length.
        geom=[p for i,p in enumerate(geom) if i==0 or p!=geom[i-1]]
        meters=_geometry_length(geom)
        if meters>self.cap:
            return None
        connectors=haversine(c.lat,c.lon,*start)+haversine(*self.snap,*self.dest)
        uncertain=connectors>.5 or any(g.ways[g.edges[ei].way_id].tags.get('sidewalk') not in ('both','left','right','yes','separate')
                                       and g.ways[g.edges[ei].way_id].kind!='foot' for ei in edges)
        return {'geometry':geom,'edges':edges,'meters':meters,'unverified':uncertain,
                'note':'Chưa xác minh lối nối, vỉa hè và chỗ qua đường' if uncertain else None}


# ---- plan -------------------------------------------------------------------------

@dataclass
class Candidate:
    kind: str                 # door | street | lot
    lat: float
    lon: float
    name: str
    way_id: int | None
    edge_idx: int | None = None
    offset: float = 0.0       # from edge.u
    walk_m: float = INF
    walk_node: int | None = None
    walk_tail: float = 0.0
    lot: dict | None = None
    entrance: int | None = None
    data: dict = field(default_factory=dict)


def _fmt_t(t: datetime) -> str:
    return t.astimezone(VN_TZ).strftime("%H:%M")


@request_cache
def plan(dest_lat: float, dest_lon: float, vehicle_id: str, intent: str, arrive_at: datetime | None,
         dwell_min: int | None, rain_scenario: list[dict] | None = None, dest_label: str = "",
         _nested: bool = False, origin: tuple[float, float] | None = None) -> dict:
    p = get_profile(vehicle_id)
    arrive = (arrive_at or datetime.now(VN_TZ)).astimezone(VN_TZ)
    dwell = dwell_min if dwell_min is not None else (PICKUP_DWELL_MIN if intent == "pickup" else 120)
    if dwell < 0:
        raise ValueError("Dwell duration must be nonnegative")
    depart = arrive + timedelta(minutes=dwell)
    stay_times = [arrive + timedelta(minutes=m) for m in range(0, dwell + 1, 15)] + [depart]
    rain = rain_scenario or []
    stay_times = sorted(set(stay_times) | set(evaluation_times(arrive, depart, rain)))
    cap = WALK_CAP_M[intent]

    g, wrs, fps = area(dest_lat, dest_lon)
    fit, fit_notes = compute_fit(g, wrs, p)
    paid = parking_data.paid_street_ways(g)

    def flood_at(times):
        return {wid: worst_over(fps.get(wid), times, rain, p.safe_water_depth, g.ways[wid].name) for wid in g.ways}

    fl_arr, fl_dep, fl_stay = flood_at([arrive]), flood_at([depart]), None
    arr = ext = _DriveSearch(g, wrs, fit, p, fl_arr, fl_dep)

    walks = _WalkSearch(g, dest_lat, dest_lon, cap)
    de, doff, ddist = _project(g, dest_lat, dest_lon, lambda w: _car_way_allowed(w))
    cands: list[Candidate] = []

    def add_candidate(c):
        path = walks.path(c)
        if path is not None:
            c.walk_m = path['meters']
            c.data['walk_path'] = path
            cands.append(c)

    if de is not None and ddist <= 35:
        la, lo = _interp(g, de.u, de.v, doff, de.length)
        add_candidate(Candidate('door', la, lo, 'Trước cửa nhà', de.way_id, de.idx, doff))
    for e in g.edges:
        w = g.ways[e.way_id]
        if not _car_way_allowed(w) or not _foot_allowed(w):
            continue
        if min(walks.dist.get(e.u, INF), walks.dist.get(e.v, INF)) > cap and (walks.edge is None or walks.edge.idx!=e.idx):
            continue
        offs = [e.length/2] if e.length<16 else [8.0,e.length/2,e.length-8.0]
        for off in offs:
            la,lo=_interp(g,e.u,e.v,off,e.length)
            add_candidate(Candidate('street',la,lo,g.display_name(w.id),w.id,e.idx,off))
    for lot in parking_data.lots_near(g, dest_lat, dest_lon, radius=cap+150):
        ent,ent_d=g.nearest_node(lot['lat'],lot['lon'],lambda n:n in arr.adj)
        if ent is not None and ent_d<=80:
            add_candidate(Candidate('lot',lot['lat'],lot['lon'],lot['name'],None,lot=lot,
                                    entrance=ent,data={'entrance_d':ent_d}))

    # ---- evaluate each candidate
    results, rejected = [], []
    door_eval = None
    for c in cands:
        r = _evaluate(c, g, wrs, fps, fit, fit_notes, paid, p, intent, arrive, depart, stay_times, rain,
                      arr, ext, fl_arr, fl_dep)
        if c.kind == "door":
            door_eval = r
        (results if r["ok"] else rejected).append(r)

    results.sort(key=lambda r: (r["tier"], r["walk"]["meters"]))
    chosen = []
    for r in results:
        same_way = r.get("way_id") and any(c.get("way_id") == r["way_id"] for c in chosen)
        if not same_way and all(haversine(r["lat"], r["lon"], c["lat"], c["lon"]) > 45 for c in chosen):
            chosen.append(r)
        if len(chosen) == 3:
            break
    for i, r in enumerate(chosen, 1):
        r["rank"] = i
        r["walk"]["geometry"] = r["_c"].data["walk_path"]["geometry"]
        r["walk"]["wade"] = _walk_wade(g, fps, r["_c"], {}, arrive, rain)
    for r in results + rejected:
        r.pop("_c", None)

    std = _standard_route(g, de, doff, fit, wrs)
    if GOONG_API_KEY and std and not _nested:
        start = origin or (std["geometry"][0][1], std["geometry"][0][0])
        goong = goong_standard_route(g, start, (dest_lat, dest_lon), fit, wrs, GOONG_API_KEY)
        if goong:
            std = goong
    if origin and GOONG_API_KEY and not _nested:
        _add_trips(chosen, origin)

    verdict = _verdict(chosen, door_eval, intent, cap)
    if not chosen and (walks.edge is None or de is None or not arr.main):
        verdict.update(coverage="unknown", headline="Chưa thể ước tính đường đi — độ tin cậy thấp",
                       detail="Thiếu mạng đường ô tô, đường đi bộ hoặc kết nối đường chính để lập điểm dừng.",
                       estimate={"answer":"unknown", "confidence":"low", "basis":"Thiếu mạng đường vào/ra hoặc đi bộ"},
                       unverified_reasons=["Thiếu mạng đường vào/ra hoặc đi bộ"])
    timing = None
    if (not _nested and door_eval and not door_eval['ok'] and
            door_eval['legality']['status']=='Permitted' and
            not door_eval.get('unverified_reasons') and any(v[0]=='blocked' for v in fl_dep.values())):
        # Every proposed time is checked against this destination and the actual
        # full engine, including the revised dwell, route, exit and legal checks.
        def recheck(leave):
            minutes=int((leave-arrive).total_seconds()//60)
            if minutes<0:
                return None
            alt=plan(dest_lat,dest_lon,vehicle_id,intent,arrive,minutes,rain,dest_label,_nested=True)
            target=alt.get('door')
            if not target or not target['ok'] or target['flood']['stay']['status']!='passable':
                return None
            wo=target['way_out']
            if wo['mode'] not in ('through','turn_here') or wo.get('manoeuvre_status')=='unknown':
                return None
            if target.get('unverified_reasons'):
                return None
            return {'headline':alt['verdict']['headline'],'code':alt['verdict']['code'],
                    'checked_departure':leave.isoformat()}
        timing=_flood_timing(p,arrive,depart,rain,recheck=recheck)
        if timing:
            parts=[]
            if timing.get('leave_before'):
                parts.append(f"rời trước {timing['leave_before']}")
            if timing.get('or_after'):
                parts.append(f"ở lại tới sau {timing['or_after']}")
            verdict['timing']='Đã kiểm tra lại toàn bộ kế hoạch theo mô hình: '+', hoặc '.join(parts)+'.'

    return {
        "destination": {"lat": dest_lat, "lon": dest_lon, "label": dest_label},
        "vehicle": p.to_json(),
        "intent": intent,
        "window": {"arrive": arrive.isoformat(), "depart": depart.isoformat(), "dwell_min": dwell,
                   "tide_arrive": _tide_json(arrive), "tide_depart": _tide_json(depart), "rain": rain},
        "verdict": verdict,
        "timing": timing,
        "stop_points": chosen,
        "door": door_eval,
        "standard_route": std,
        "layers": _layers(g, wrs, fit, fit_notes, fps, dest_lat, dest_lon, arrive, depart, rain, p),
        "area_source": g.source,
        "counts": {"candidates": len(cands), "passed": len(results), "rejected": len(rejected)},
    }


def _flood_timing(p: VehicleProfile, arrive, depart, rain, *, recheck=None) -> dict | None:
    """No generic tide proxy: only publish alternatives accepted by the full planner.

    Search is bounded to two hours earlier / twelve hours later. Unknown or
    otherwise failed plans produce no timing instruction.
    """
    if recheck is None:
        return None
    result={}
    for direction,key,label in [(-1,'leave_before','if_leave_before'),(1,'or_after','if_stay_until')]:
        steps=8 if direction<0 else 48
        for step in range(1,steps+1):
            leave=depart+timedelta(minutes=15*direction*step)
            if leave<=arrive:
                break
            checked=recheck(leave)
            if checked:
                result[key]=_fmt_t(leave)
                result[label]=checked
                break
    return result or None


def _tide_json(t):
    lvl = tide_level(t)
    return {"level_m": None if lvl is None else round(lvl, 2), "alarm": alarm_label(lvl)}


CONFIDENCE_VI = {"high": "cao", "medium": "trung bình", "low": "thấp"}


def _width_estimate(wr):
    """A point hypothesis inside the fused range, never a certified lower bound."""
    if wr.review or wr.top_tier is None:
        return None
    samples = [b.estimate_m for b in wr.evidence if b.tier == wr.top_tier and b.estimate_m is not None and b not in wr.overruled]
    if samples:
        return max(wr.lo, min(wr.hi, min(samples)))
    if wr.lo == 0 and wr.hi >= 40:
        # An unresolved survey can retain a weak prior for estimation only.
        priors = [b for b in wr.evidence if b.lo > 0 and b not in wr.overruled]
        if not priors:
            return None
        b = priors[0]
        return (b.lo + min(b.hi, b.lo + 3)) / 2
    return (wr.lo + min(wr.hi, wr.lo + 3)) / 2


def _estimate(c, g, wrs, p, checks, failures):
    """D47: useful hypothesis + ordinal evidence confidence; hard checks are unchanged."""
    route, wo = checks['route_in'], checks['way_out']
    segments = {}
    for ei, length in (route or {}).get('_segments', []) + wo.get('_segments', []):
        segments[ei] = max(segments.get(ei, 0), length)
    if c.way_id is not None and c.edge_idx is not None:
        segments.setdefault(c.edge_idx, .01)
    total = sum(segments.values())
    widths = [wrs[g.edges[ei].way_id] for ei in segments]
    values = [_width_estimate(wr) for wr in widths]
    strong_m = quantitative_m = 0.0
    measured = 0
    for (ei, length), wr in zip(segments.items(), widths):
        numeric = [b for b in wr.evidence if b.tier in ('Measured', 'Official', 'Observed')
                   and (b.estimate_m is not None or (b.hi < 40 and b.hi > 0 and
                        b.measurement_schema != 'parcel-survey-unresolved-v2'))]
        if numeric:
            measured += 1
            quantitative_m += length
        if wr.top_tier in ('Measured', 'Official') and wr.lo > 0 and not wr.review and (
                not wr.evidence or any(b.tier == wr.top_tier and b.coverage_complete for b in wr.evidence)):
            strong_m += length
    coverage = {'sampled_segments': measured, 'total_segments': len(segments),
                'sample_supported_fraction': round(quantitative_m / total, 3) if total else 0,
                'complete_strong_fraction': round(strong_m / total, 3) if total else 0,
                'scope': 'Đoạn trên đường vào/ra có mẫu bề rộng; mẫu rời không bảo đảm toàn đoạn'}
    # Passage uses tight_min; opening the door uses the separate stop threshold.
    stop_value = _width_estimate(wrs[c.way_id]) if c.way_id is not None else None
    if not widths or any(v is None for v in values):
        answer = 'unknown'
    elif min(values) >= p.fits_min and (stop_value is None or stop_value >= p.door_min):
        answer = 'fits'
    else:
        # A point below a threshold is a low-confidence negative, not a hard exclusion.
        answer = 'tight' if min(values) >= p.tight_min and (stop_value is None or stop_value >= p.door_min) else 'no'
    if failures:
        answer = 'no'
    confidence = 'low'
    legal = checks['legality']
    flood = checks['flood']['stay']['status']
    if total and quantitative_m / total >= .5 and not any(w.review for w in widths):
        confidence = 'medium'
    threshold_clear = all(wr.lo >= p.fits_min for wr in widths) and (
        c.way_id is None or wrs[c.way_id].lo >= p.door_min)
    if (total and strong_m / total >= 1 - 1e-9 and threshold_clear and route and route.get('strict')
            and wo.get('strict') and flood == 'passable' and legal['status'] == 'Permitted'
            and not c.data.get('walk_path', {}).get('unverified', True)):
        confidence = 'high'
    if answer == 'unknown' or wo['mode'] in ('unknown', 'none') or any(w.review for w in widths):
        confidence = 'low'
    hard_legal = legal['status'] in ('Prohibited', 'Restricted')
    hard_width = any(not wr.review and any(
        b.tier in ('Measured', 'Official') and b not in wr.overruled and
        b.hi < (p.door_min if g.edges[ei].way_id == c.way_id else p.tight_min)
        for b in wr.evidence) for ei, wr in zip(segments, widths))
    if hard_legal or hard_width or flood == 'blocked':
        answer, confidence = 'no', 'high'
    elif not route or failures:
        confidence = 'low'
    if c.kind == 'lot' and not failures:
        answer = 'unknown'  # no measured entrance / internal manoeuvre envelope
    tier_names = {'Measured':'đo thực tế', 'Official':'địa chính / chính thức', 'Observed':'quan sát',
                  'Declared':'tin rao / tự khai', 'Inferred':'suy luận'}
    finite = [(v, wr) for v, wr in zip(values, widths) if v is not None]
    if finite:
        value, limiting = min(finite, key=lambda x: x[0])
        tier = limiting.top_tier
        if limiting.lo == 0 and limiting.hi >= 40 and not any(b.estimate_m is not None for b in limiting.evidence):
            tier = next((b.tier for b in limiting.evidence if b.lo > 0 and b not in limiting.overruled), tier)
        basis = [f"{tier_names.get(tier, 'thiếu nguồn')} ≈{value:.1f} m".replace('.', ',')]
    else:
        basis = ['chưa có bề rộng đủ để ước lượng']
    basis.append(f"{measured}/{len(segments)} đoạn có mẫu đo ({coverage['sample_supported_fraction']:.0%} chiều dài có mẫu)")
    if strong_m < total:
        basis.append('chưa đo kín tuyến')
    if wo['mode'] == 'unknown' or wo.get('manoeuvre_status') == 'unknown':
        basis.append('chưa rõ đường ra / thao tác rẽ')
    if flood in ('unknown', 'risky'):
        basis.append('chưa rõ ngập' if flood == 'unknown' else 'có thể ngập')
    if legal['status'] == 'Unverified':
        basis.append('chưa xác minh pháp lý')
    if hard_legal:
        basis.extend(r['text'] + ' (' + r['citation'] + ')' for r in legal['rules']
                     if r['status'] in ('Prohibited', 'Restricted'))
    elif failures:
        basis.append(failures[0])
    return {'answer': answer, 'confidence': confidence, 'basis': ' · '.join(basis), 'coverage': coverage}


def _evaluate(c, g, wrs, fps, fit, fit_notes, paid, p, intent, arrive, depart, stay_times, rain,
              arr, ext, fl_arr, fl_dep) -> dict:
    checks, reasons_fail, unverified = {}, [], []
    tier_bump = 0
    if c.data.get("walk_path", {}).get("unverified"):
        unverified.append(c.data["walk_path"]["note"])
    way_id = c.way_id if c.kind != "lot" else None

    # 1. Route in (on the Fit Network, flood at arrival).
    if isinstance(arr, _DriveSearch):
        pairs = [(r, arr.exit(c, r)) for r in arr.arrival_options(c)]
        viable = [(r, e) for r, e in pairs if e["mode"] != "none"]
        def plausible(pair):
            segments = pair[0].get('_segments', []) + pair[1].get('_segments', [])
            return bool(segments) and all((_width_estimate(wrs[g.edges[ei].way_id]) or 0) >= p.tight_min
                                          for ei, _ in segments)
        # A smaller car's larger permissive network may choose a short, doubtful
        # bottleneck. Look for a plausible detour before giving a negative estimate.
        # This search only removes doubtful edges; it never relaxes a Hard Check.
        if viable and not any(plausible(pair) for pair in viable):
            if not hasattr(arr, 'estimate_search'):
                arr.estimate_search = _DriveSearch(g, wrs, fit, p, fl_arr, fl_dep, estimate_only=True)
            alternate = arr.estimate_search
            viable += [(r, e) for r in alternate.arrival_options(c)
                       if (e := alternate.exit(c, r))['mode'] != 'none']
        route, selected_exit = min(viable or pairs, key=lambda pair: (
            not (pair[0]["strict"] and pair[1]["strict"]),
            pair[1].get("tight_exit", False), not plausible(pair), pair[0]["meters"]), default=(None, None))
    else:
        route, selected_exit = _route_in(c, g, arr), None
    if route is None:
        reasons_fail.append("Không có đường vào phù hợp với xe (hẻm hẹp hoặc ngập lúc đến)")
    elif not route["strict"]:
        unverified.append("Đường vào đi qua đoạn chưa đủ bằng chứng (bề rộng hoặc ngập)")
    checks["route_in"] = route

    # 2. Fit at the stop itself + door opening (street stops only).
    if way_id is not None:
        wr = wrs[way_id]
        fc = fit[way_id]
        fitj = {"class": fc, "width_range": wr.to_json(), "note": fit_notes.get(way_id),
                "needed": {"fits_min": round(p.fits_min, 2), "tight_min": round(p.tight_min, 2),
                           "door_min": round(p.door_min, 2)}}
        if fc in ("no", "blocked"):
            reasons_fail.append(fit_notes.get(way_id) or
                                f"{wr.label} {wr.lo:.1f}–{min(wr.hi, 40):.1f} m, xe cần ≥ {p.tight_min:.2f} m")
        elif fc == "unknown":
            unverified.append(f"Chưa đủ bằng chứng bề rộng ({wr.lo:.1f}–{min(wr.hi, 40):.1f} m; xe cần ≥ {p.tight_min:.2f} m)")
        elif fc == "tight":
            tier_bump = max(tier_bump, 0)
        if wr.hi < p.door_min:
            reasons_fail.append(f"Không đủ chỗ mở cửa xe (cần {p.door_min:.2f} m)")
        elif wr.lo < p.door_min and fc != "no":
            unverified.append(f"Chưa chắc đủ chỗ mở cửa xe (cần {p.door_min:.2f} m)")
        checks["fit"] = fitj
    else:
        checks["fit"] = {"class": "lot", "note": "Bãi đỗ ngoài đường"}

    # 3. Way Out (at departure).
    wo = selected_exit or _way_out(c, g, wrs, fit, p, ext, route)
    checks["way_out"] = wo
    if wo["mode"] == "none":
        reasons_fail.append(wo["text"])
    elif not wo["strict"]:
        unverified.append("Đường ra lúc rời đi chưa đủ bằng chứng")
    if wo.get("tight_exit"):
        tier_bump = 1

    # 4. Flood at the stop over the whole Dwell Window.
    prof = fps.get(way_id) if way_id is not None else (fps.get(g.edges[g.drive_adj[c.entrance][0][0]].way_id)
                                                        if c.entrance in g.drive_adj else None)
    st, d, t = worst_over(prof, stay_times, rain, p.safe_water_depth, g.ways[way_id].name if way_id else "")
    flood = {"stay": {"status": st, "depth": d.to_json() if d else None, "at": _fmt_t(t) if t else None},
             "arrival_route": route["flood"] if route else None, "exit_route": wo.get("flood")}
    if st == "blocked":
        reasons_fail.append(f"Điểm dừng ngập {d.lo * 100:.0f}–{d.hi * 100:.0f} cm lúc {_fmt_t(t)} "
                            f"({', '.join(d.drivers)}), quá mức an toàn {p.safe_water_depth * 100:.0f} cm của xe")
    elif st == "risky":
        unverified.append(f"Có thể ngập {d.lo * 100:.0f}–{d.hi * 100:.0f} cm lúc {_fmt_t(t)}")
    elif st == "unknown":
        unverified.append("Chưa đủ dữ liệu ngập: " + "; ".join(d.unknown_reasons if d else ["Thiếu hồ sơ hoặc dự báo"]))
    checks["flood"] = flood

    # 5. Stop Legality.
    if c.kind == "lot":
        lstatus, rules = legality_for_lot(c.lot, intent)
    else:
        e = g.edges[c.edge_idx]
        dj = junction_distance(g, e, c.offset, wrs)
        lstatus, rules = legality_on_street(g, g.ways[way_id], wrs[way_id], c.lat, c.lon, dj, intent, arrive,
                                            paid.get(way_id), until=depart)
    checks["legality"] = {"status": lstatus, "rules": [r.to_json() for r in rules]}
    if lstatus == "Prohibited" or (intent == "park" and lstatus == "Restricted"):
        reasons_fail.append("; ".join(r.text for r in rules if r.status in ("Prohibited", "Restricted")))
    elif lstatus == "Unverified":
        unverified.append("Chưa đủ dữ liệu pháp lý: " + "; ".join(r.text for r in rules if r.status == "Unverified"))

    # Ranking tiers (Q6, Q7): verified → verified with a tight exit → Restricted or Unverified.
    tier = 2 if (lstatus == "Restricted" or unverified) else tier_bump
    ok = not reasons_fail
    walk_min = c.walk_m / WALK_SPEED / 60
    return {
        "ok": ok, "kind": c.kind, "name": c.name, "lat": c.lat, "lon": c.lon, "way_id": way_id,
        "tier": tier, "verified": ok and tier <= 1,
        "badges": _badges(checks, tier, lstatus),
        "walk": {"meters": round(c.walk_m), "verified": not c.data.get("walk_path", {}).get("unverified", True), "minutes": max(1, round(walk_min)) if c.walk_m > 20 else 0},
        "route_in": route and {k: v for k, v in route.items() if k != "strict" and not k.startswith('_')},
        "fit": checks["fit"], "way_out": {k: v for k, v in wo.items() if k != "strict" and not k.startswith('_')},
        "flood": flood, "legality": checks["legality"],
        "estimate": _estimate(c, g, wrs, p, checks, reasons_fail),
        "fail_reasons": reasons_fail, "unverified_reasons": unverified, "lot": c.lot, "_c": c,
    }


def _route_in(c: Candidate, g: AreaGraph, arr) -> dict | None:
    for strict in (True, False):
        dist, pred = arr[strict]
        if c.kind == "lot":
            n = c.entrance
            if n in dist:
                nodes = _path_nodes(pred, n)[::-1]
                return {"strict": strict and c.data.get("entrance_d", 0) <= .5, "meters": round(_geometry_length(_coords(g,nodes)+[[c.lon,c.lat]])),
                        "geometry": _coords(g, nodes) + [[c.lon, c.lat]], "flood": None}
            continue
        e = g.edges[c.edge_idx]
        w = g.ways[e.way_id]
        opts = []
        if e.u in dist and w.oneway >= 0:
            opts.append((dist[e.u] + c.offset, e.u, "u"))
        if e.v in dist and w.oneway <= 0:
            opts.append((dist[e.v] + e.length - c.offset, e.v, "v"))
        if opts:
            dmin, n, side = min(opts)
            nodes = _path_nodes(pred, n)[::-1]
            return {"strict": strict, "meters": round(_geometry_length(_coords(g,nodes)+[[c.lon,c.lat]])), "side": side,
                    "geometry": _coords(g, nodes) + [[c.lon, c.lat]], "flood": None}
    return None


def _way_out(c: Candidate, g: AreaGraph, wrs, fit, p: VehicleProfile, ext, route) -> dict:
    if route is None:
        return {"mode": "none", "text": "Không vào được nên không xét đường ra", "strict": False}
    if isinstance(ext, _DriveSearch):
        return ext.exit(c, route)
    # Compatibility for diagnostic callers supplying legacy node search trees.
    flood_map = {wid: ('passable', None, None) for wid in g.ways}
    return _DriveSearch(g, wrs, fit, p, flood_map, flood_map).exit(c, route)


def _badges(checks, tier, lstatus) -> list[str]:
    out = []
    fc = checks["fit"]["class"]
    out.append({"fits": "Vừa xe", "tight": "Chật", "unknown": "Chưa rõ bề rộng", "lot": "Bãi đỗ"}.get(fc, fc))
    wo = checks["way_out"]
    if wo["mode"] != "none" and not wo.get("strict", False):
        out.append("Chưa xác minh đường ra")
    else:
        out.append({"through": "Đi thẳng ra", "turn_here": "Quay đầu tại chỗ", "lot": "Quay đầu trong bãi",
                    "unknown": "Chưa xác minh thao tác ra", "reverse": f"Lùi {wo.get('reverse_m', 0)} m"}.get(wo["mode"], "Không có đường ra"))
    out.append({"passable": "Trong mức nước theo mô hình", "unknown": "Chưa rõ ngập", "risky": "Có thể ngập", "blocked": "Ngập"}[checks["flood"]["stay"]["status"]])
    if lstatus == "Unverified":
        codes = {r["code"] for r in checks["legality"]["rules"] if r["status"] == "Unverified"}
        out.append("Chưa rõ đủ 2 làn xe" if "lane-unknown" in codes else "Chưa xác minh pháp lý")
    else:
        out.append({"Permitted": "Được phép", "Restricted": "Hạn chế theo luật", "Prohibited": "Cấm"}[lstatus])
    return out


def _walk_geometry(g, c: Candidate, wpred, dlat, dlon):
    if 'walk_path' not in c.data:
        c.data['walk_path'] = _WalkSearch(g,dlat,dlon,INF).path(c)
    return (c.data['walk_path'] or {}).get('geometry', [])


def _walk_wade(g, fps, c: Candidate, wpred, arrive, rain):
    worst = None
    for ei in (c.data.get('walk_path') or {}).get('edges', []):
        wid=g.edges[ei].way_id
        d=depth_at(fps.get(wid),arrive,rain,g.ways[wid].name)
        if d and d.hi>WALK_WADE_M and (worst is None or d.hi>worst['hi']):
            worst={'lo':round(d.lo,2),'hi':round(d.hi,2),'street':g.ways[wid].name,'label':'Lội nước'}
    return worst


def _verdict(chosen, door_eval, intent, cap) -> dict:
    if not chosen:
        return {"code": "none", "headline": f"Không tìm thấy điểm dừng phù hợp trong {cap:.0f} m đi bộ — độ tin cậy thấp",
                "detail": "; ".join((door_eval or {}).get('fail_reasons', [])), "verified": False,
                "unverified_reasons": (door_eval or {}).get('unverified_reasons', []),
                "estimate": {"answer":"no", "confidence":"low", "basis":"Không có điểm vượt qua các kiểm tra trong mạng đường hiện có"}}
    best = chosen[0]
    verb = "đỗ" if intent == "park" else "dừng đón/trả"
    estimate = best.get('estimate') or {'answer':'unknown', 'confidence':'low', 'basis':'Thiếu bằng chứng bề rộng'}
    code = ('door' if best['kind'] == 'door' else 'nearby') if best['verified'] else 'unverified'
    detail = best.get('way_out', {}).get('text', '')
    if best['legality']['status'] == 'Restricted':
        head = f"Luật cấm dừng tại {best['name']}"
        detail = '; '.join(r['text'] + ' (' + r['citation'] + ')' for r in best['legality']['rules']
                           if r['status'] == 'Restricted')
        if not best.get('estimate'):
            estimate = {'answer':'no', 'confidence':'high', 'basis':detail}
    elif estimate['answer'] == 'no':
        head = f"Ước tính xe khó dừng tại {best['name']}, cách cửa {best['walk']['meters']} m"
    elif best['kind'] == 'door':
        head = "Có thể vào tận cửa" if estimate['answer'] == 'fits' else "Ước tính vào tận cửa khá chật"
        if estimate['answer'] == 'unknown':
            head = 'Ước tính có thể tới cửa, còn thiếu bề rộng'
    else:
        head = f"Nên {verb} ở {best['name']}, đi bộ {best['walk']['meters']} m"
        if estimate['answer'] == 'tight':
            head += ' (khá chật)'
        if door_eval and not door_eval['ok']:
            rules = [r['text'] + ' (' + r['citation'] + ')' for r in door_eval['legality']['rules']
                     if r['status'] in ('Prohibited', 'Restricted')]
            detail = 'Tại cửa: ' + ('; '.join(rules) if rules else '; '.join(door_eval['fail_reasons']))
    return {'code':code, 'headline':head + ' — độ tin cậy ' + CONFIDENCE_VI[estimate['confidence']],
            'detail':detail, 'estimate':dict(estimate), 'verified':best['verified'],
            'unverified_reasons':list(best.get('unverified_reasons', []))}


def _decode_polyline(s: str) -> list[list[float]]:
    coords, idx, lat, lon = [], 0, 0, 0
    while idx < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += d
            else:
                lon += d
        coords.append([lon / 1e5, lat / 1e5])
    return coords


def goong_drive(origin, dest) -> dict | None:
    """Goong Direction v2 car route: geometry [[lon, lat]…], distance (m) and duration (s)."""
    import httpx
    try:
        r = httpx.get("https://rsapi.goong.io/v2/direction",
                      params={"api_key": GOONG_API_KEY, "origin": f"{origin[0]},{origin[1]}",
                              "destination": f"{dest[0]},{dest[1]}", "vehicle": "car"}, timeout=15).json()
        leg = r["routes"][0]["legs"][0]
        coords = []
        for step in leg["steps"]:
            coords += _decode_polyline(step["polyline"]["points"])
        return {"geometry": coords, "distance_m": leg["distance"]["value"], "duration_s": leg["duration"]["value"]}
    except Exception:
        return None


ALLEY_SPEED = 15 / 3.6  # m/s for the last stretch inside alleys


def _add_trips(chosen: list[dict], origin) -> None:
    """Whole trip per Stop Point: Goong drives from the origin to where our last stretch starts."""
    from concurrent.futures import ThreadPoolExecutor

    def leg_for(sp):
        g_in = (sp.get("route_in") or {}).get("geometry") or []
        handoff = (g_in[0][1], g_in[0][0]) if g_in else (sp["lat"], sp["lon"])
        return goong_drive(origin, handoff)

    with ThreadPoolExecutor(3) as pool:
        legs = list(pool.map(leg_for, chosen))
    for sp, leg in zip(chosen, legs):
        if not leg:
            continue
        last = (sp.get("route_in") or {}).get("meters") or 0
        drive_s = leg["duration_s"] + last / ALLEY_SPEED
        sp["approach"] = {"geometry": leg["geometry"], "source": "Goong Direction v2 (car)"}
        sp["trip"] = {"drive_m": round(leg["distance_m"] + last), "drive_min": max(1, round(drive_s / 60)),
                      "walk_m": sp["walk"]["meters"], "walk_min": sp["walk"]["minutes"],
                      "total_min": max(1, round(drive_s / 60)) + sp["walk"]["minutes"]}


def goong_standard_route(g, origin, dest, fit, wrs, key: str) -> dict | None:
    """Goong's own car route, with the alleys it uses that don't (or may not) fit this vehicle."""
    leg = goong_drive(origin, dest)
    if not leg:
        return None
    coords = leg["geometry"]
    # Snap the route's points near the destination to ways; a way counts only if the route runs along it
    # (2+ points), not if it merely passes the mouth of a side alley at a junction.
    hits: dict[int, int] = {}
    order: list[int] = []
    for lon, lat in _densify(coords, 10.0):
        if haversine(lat, lon, dest[0], dest[1]) > 800:
            continue
        best, bd = None, 6.0
        for wid in _ways_near(g, lat, lon):
            w = g.ways[wid]
            d = min(haversine(lat, lon, *g.nodes[n]) for n in w.nodes)
            if d < bd:
                best, bd = wid, d
        if best:
            hits[best] = hits.get(best, 0) + 1
            if best not in order:
                order.append(best)
    bad = []
    for wid in order:
        if hits[wid] >= 2 and fit.get(wid) in ("no", "blocked", "unknown") and g.ways[wid].kind != "main":
            wr = wrs[wid]
            bad.append({"way_id": wid, "name": g.display_name(wid), "label": wr.label, "fit": fit[wid],
                        "lo": round(wr.lo, 2), "hi": None if wr.hi >= 40 else round(wr.hi, 2)})
    return {"geometry": coords, "unfit_ways": bad, "source": "Goong Direction v2 (car)",
            "distance_m": leg["distance_m"], "duration_s": leg["duration_s"],
            "note": "Tuyến ô tô của Goong: không tính bề rộng hẻm và ngập"}


def _densify(coords: list[list[float]], step_m: float) -> list[list[float]]:
    """Extra points every ~step_m along the polyline, so long straight segments are sampled too."""
    out = []
    for (lo1, la1), (lo2, la2) in zip(coords, coords[1:]):
        n = max(1, int(haversine(la1, lo1, la2, lo2) // step_m))
        out += [[lo1 + (lo2 - lo1) * i / n, la1 + (la2 - la1) * i / n] for i in range(n)]
    return out + coords[-1:]


_NEAR_CACHE: dict = {}


def _ways_near(g, lat, lon):
    key = (g.source, getattr(g, "_engine_revision", id(g)), round(lat, 3), round(lon, 3))
    if key not in _NEAR_CACHE:
        if len(_NEAR_CACHE) >= 256:
            _NEAR_CACHE.pop(next(iter(_NEAR_CACHE)))
        _NEAR_CACHE[key] = [wid for wid, w in g.ways.items() if w.drivable and any(
            abs(g.nodes[n][0] - lat) < 0.0012 and abs(g.nodes[n][1] - lon) < 0.0012 for n in w.nodes)]
    return _NEAR_CACHE[key]


def _standard_route(g, de, doff, fit, wrs):
    """What an ordinary car map does: shortest drivable path to the door, ignoring width and water."""
    if de is None:
        return None
    main_nodes = {n for w in g.ways.values() if w.kind == "main" and w.drivable for n in w.nodes}
    dist, pred = dijkstra(g.drive_adj, {n: 0.0 for n in main_nodes}, lambda e: True, lambda e: g.edges[e].length)
    opts = [(dist[n] + (doff if n == de.u else de.length - doff), n) for n in (de.u, de.v) if n in dist]
    if not opts:
        return None
    _, n = min(opts)
    nodes = _path_nodes(pred, n)[::-1]
    bad = []
    for a, b in zip(nodes, nodes[1:]):
        eidx = pred[b][0]
        wid = g.edges[eidx].way_id
        if fit[wid] in ("no", "blocked", "unknown") and wid not in [x["way_id"] for x in bad]:
            wr = wrs[wid]
            bad.append({"way_id": wid, "name": g.display_name(wid), "label": wr.label, "fit": fit[wid],
                        "lo": round(wr.lo, 2), "hi": None if wr.hi >= 40 else round(wr.hi, 2)})
    return {"geometry": _coords(g, nodes), "unfit_ways": bad,
            "note": "Tuyến bản đồ thông thường: đường ngắn nhất cho ô tô, không tính bề rộng hẻm và ngập"}


def _layers(g, wrs, fit, fit_notes, fps, lat, lon, arrive, depart, rain, p):
    feats, flood_feats = [], []
    for wid, w in g.ways.items():
        if not w.drivable:
            continue
        la, lo = g.nodes[w.nodes[len(w.nodes) // 2]]
        if haversine(lat, lon, la, lo) > 750:
            continue
        wr = wrs[wid]
        coords = g.way_coords(wid)
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"way_id": wid, "name": w.name, "kind": w.kind, "fit": fit[wid],
                                     "label": wr.label, "lo": round(wr.lo, 2),
                                     "hi": None if wr.hi >= 40 else round(wr.hi, 2),
                                     "top_tier": wr.top_tier, "review": wr.review, "note": fit_notes.get(wid)}})
        prof = fps.get(wid)
        da, dd = depth_at(prof, arrive, rain, w.name), depth_at(prof, depart, rain, w.name)
        if prof or da or dd:
            flood_feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                                "properties": {"way_id": wid, "name": w.name, "records": len(prof.records) if prof else 0,
                                               "inferred_from": prof.inferred_from if prof else "",
                                               "arrive": da.to_json() if da else None,
                                               "depart": dd.to_json() if dd else None,
                                               "status_arrive": flood_status(da, p.safe_water_depth),
                                               "status_depart": flood_status(dd, p.safe_water_depth)}})
    return {"fit": {"type": "FeatureCollection", "features": feats},
            "flood": {"type": "FeatureCollection", "features": flood_feats}}


def way_evidence(lat: float, lon: float, way_id: int) -> dict:
    g, wrs, fps = area(lat, lon)
    w = g.ways[way_id]
    prof = fps.get(way_id)
    return {"way_id": way_id, "name": g.display_name(way_id), "tags": w.tags, "osm_url": f"https://www.openstreetmap.org/way/{way_id}",
            "width_range": wrs[way_id].to_json(),
            "flood_history": {"records": [r.to_json() for r in prof.records] if prof else [],
                              "inferred_from": prof.inferred_from if prof else ""}}
