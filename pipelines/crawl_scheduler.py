"""Bounded fair scheduling: one two-cut deep turn, four ring ways, eight city ways.

Cache-only passes continue during shared portal cooldowns. Extra ring cuts are
accepted only when entirely answerable offline, so they never add HTTP requests.
"""
from __future__ import annotations
import collections
from shapely.geometry import LineString
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from app import osm, parcels, portal_gate
import campus_priority
import osm_city_cache


class CacheMiss(parcels.Unavailable):
    pass


def cached_lookup(lookup):
    def query(lat, lon):
        hit, result = lookup.lookup(lat, lon)
        if not hit:
            raise CacheMiss('Unknown point remains retryable')
        return result
    return query


def breadth_measure(coords, lookup, offline=False):
    query = cached_lookup(lookup) if offline else lookup
    centre = parcels.measure(coords, fractions=(.5,), parcel_lookup=query)
    # Try the extra cuts offline only. Never replace a centre result if they miss.
    try:
        extra = parcels.measure(coords, fractions=(.1, .5, .9), parcel_lookup=cached_lookup(lookup))
        if extra:
            return extra, 3
    except parcels.Unavailable:
        pass
    return centre, 1


def deep_chunk(coords, lookup, partial=None, offline=False, budget=2):
    """At most two 5 m cuts per turn; unfinished work cannot starve breadth."""
    partial = partial or {"next": 0, "cuts": []}
    lat, lon = coords[0]
    line = LineString([parcels._local(lo, la, lat, lon) for la, lo in coords])
    total = campus_priority.cut_count(coords)
    end = min(total, partial["next"] + budget)
    cuts = list(partial["cuts"])
    query = cached_lookup(lookup) if offline else lookup
    for index in range(partial["next"], end):
        result = parcels._cut_at(line, min(line.length - 1, parcels.DEEP_STEP / 2 + index * parcels.DEEP_STEP), lat, lon, query)
        if result:
            cuts.append(result)
    progress = {"next": end, "cuts": cuts, "total": total}
    result = {"samples": [cut["width_m"] for cut in cuts], "cuts": cuts} if cuts else None
    return result, end, progress if end < total else None


def update(state, cache, inner, ring):
    done = state['campus_deep_done']
    state['round3_progress'] = {
        'inner_target': len(inner), 'inner_completed': sum(w in done for w in inner),
        'inner_with_width': sum(bool(done.get(w, {}).get('with_data')) for w in inner),
        'inner_cuts_completed': sum(done[w]['attempted_cuts'] for w in inner if w in done),
        'inner_partial_ways': sum(w in inner for w in state.get('campus_deep_partial', {})),
        'inner_partial_cuts': sum(p['next'] for w,p in state.get('campus_deep_partial', {}).items() if w in inner),
        'ring_target': len(ring), 'ring_completed': sum(w in cache for w in ring),
        'ring_with_width': sum(bool(cache.get(w)) for w in ring),
        'city_completed': sum(w not in inner and w not in ring for w in cache),
        'city_with_width': sum(bool(value) and w not in inner and w not in ring for w, value in cache.items())}
    for ident, info in state['campuses'].items():
        ids = set(state['campus_inner_targets'][ident]); rings = set(state['campus_ring_targets'][ident])
        completed = ids & done.keys()
        info.update({'inner_completed': len(completed),
                     'inner_with_width': sum(bool(done[w]['with_data']) for w in completed),
                     'inner_cuts_completed': sum(done[w]['attempted_cuts'] for w in completed),
                     'ring_completed': sum(w in cache for w in rings),
                     'ring_with_width': sum(bool(cache.get(w)) for w in rings),
                     'ways_with_cadastral_width': sum(bool(cache.get(w)) for w in ids | rings),
                     'ways_deep_completed': len(completed), 'ways_deep_with_width': sum(bool(done[w]['with_data']) for w in completed)})
        if ids <= done.keys() and not info.get('inner_finished_at'):
            info['inner_finished_at'] = campus_priority.now()


class CityQueue:
    def __init__(self, state, cache, excluded, points, schedule, stop, log, batch=12):
        self.state, self.cache, self.excluded = state, cache, excluded
        self.points, self.schedule, self.stop, self.log = points, schedule, stop, log
        self.index, self.queue, self.batch = 0, collections.deque(), batch
        self.sweep_pending = False
        self.finished = False

    def next(self):
        from crawl_city import candidates
        while not self.queue and not self.finished and not self.stop.is_set():
            if self.index == len(self.points):
                if not self.sweep_pending:
                    self.finished = True
                    return None
                self.index, self.sweep_pending = 0, False
            lat, lon = self.points[self.index]; self.index += 1
            key = osm.area_key(lat, lon)
            if key in self.state['cells_done']:
                continue
            try:
                osm_city_cache.ensure(lat, lon, self.stop, force_fresh=True)
                graph = osm.cached_graph(lat, lon)
                if graph is None:
                    raise RuntimeError('Missing materialized graph')
            except Exception as exc:
                self.sweep_pending = True
                self.log.warning('CITY_MAP_RETRY cell=%s error=%s', key, type(exc).__name__)
                continue
            info = self.schedule.get(key, {})
            district = info.get('district', 'boundary')
            if key not in self.state['cells_visited']:
                self.state['cells_visited'].append(key)
            if district not in self.state['districts_visited']:
                self.state['districts_visited'].append(district)
            for way in graph.ways.values():
                wid = str(way.id)
                if way.drivable and way.kind != 'main' and wid not in self.state['ways_meta']:
                    self.state['ways_meta'][wid] = {'coords': [graph.nodes[n] for n in way.nodes],
                        'name': way.name, 'alley': way.is_alley, 'cell': key, 'district': district}
            ways = [w for w in candidates(graph, lat, lon, self.cache, info.get('district_id')) if str(w.id) not in self.excluded]
            self.sweep_pending |= bool(ways)
            self.queue.extend(str(w.id) for w in ways[:self.batch])
            self.state['cell_progress'][key] = {'remaining': len(ways), 'district': district, 'updated_at': campus_priority.now()}
            if not ways:
                self.state['cells_done'].append(key)
            osm._GRAPHS.pop(key, None)
        while self.queue:
            wid = self.queue.popleft()
            if wid not in self.cache:
                return wid
        return None


def run(state, cache, lookup, inner, ring, points, schedule, stop, save, log, guard, batch=12):
    done = state['campus_deep_done']
    partials = state.setdefault('campus_deep_partial', {})
    deferred = state.setdefault('round3_retry_after', {})
    deepq = collections.deque(sorted(inner - done.keys(), key=int))
    ringq = collections.deque(sorted(ring - cache.keys(), key=int))
    city = CityQueue(state, cache, inner | ring, points, schedule, stop, log, batch)
    pattern = ['city', 'ring', 'city', 'city', 'inner', 'city', 'ring',
               'city', 'ring', 'city', 'city', 'ring', 'city']
    turn, last_report, last_offline = 0, 0, -1
    pending = {}

    def take(kind):
        queue = deepq if kind == 'inner' else ringq
        if kind == 'city':
            wid = city.next()
            if wid is not None and any(task_wid == wid for _, task_wid in pending.values()):
                return None
            if wid is not None and deferred.get(wid, 0) > time.time():
                city.queue.append(wid)
                return None
            return wid
        for _ in range(len(queue)):
            wid = queue.popleft()
            if deferred.get(wid, 0) > time.time():
                queue.append(wid)
            else:
                return wid
        return None

    def measure(kind, wid, offline=False):
        coords = state['ways_meta'][wid]['coords']
        if kind == 'inner':
            return deep_chunk(coords, lookup, partials.get(wid), offline, budget=100000 if offline else 2)
        result, cuts = breadth_measure(coords, lookup, offline)
        return result, cuts, None

    def accept(kind, wid, result, cuts, offline=False):
        with guard:
            if result:
                value = {**result, 'deep': kind == 'inner', 'queried_at': campus_priority.now(),
                         'sample_strategy': 'campus-full-5m' if kind == 'inner' else f'{kind}-breadth-{cuts}-cuts',
                         'attempted_cuts': cuts}
                if kind == 'inner' or not (cache.get(wid) or {}).get('deep'):
                    cache[wid] = value
            elif wid not in cache:
                cache[wid] = None
            if kind == 'inner':
                done[wid] = {'finished_at': campus_priority.now(), 'attempted_cuts': cuts,
                             'with_data': bool(result), 'offline': offline}
            counters = state.setdefault('round3_completed', {'inner': 0, 'ring': 0, 'city': 0})
            counters[kind] += 1
            state.setdefault('round3_completion_events', []).append({'at': time.time(), 'kind': kind, 'wid': wid,
                                                                   'with_data': bool(result), 'cuts': cuts, 'offline': offline})

    with ThreadPoolExecutor(2) as pool:
        while not stop.is_set():
            cooldown = portal_gate.cooldown_until()
            if cooldown <= time.time():
                for _ in range(len(pattern)):
                    if len(pending) >= 2:
                        break
                    kind = pattern[turn % len(pattern)]; turn += 1
                    wid = take(kind)
                    if wid is not None:
                        pending[pool.submit(measure, kind, wid)] = (kind, wid)
            ready, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED) if pending else (set(), set())
            for future in ready:
                kind, wid = pending.pop(future)
                try:
                    result, cuts, partial = future.result()
                    if partial is not None:
                        partials[wid] = partial
                        deepq.append(wid)
                    else:
                        partials.pop(wid, None)
                        accept(kind, wid, result, cuts)
                except parcels.Blocked:
                    state['blocked'] += 1
                    deferred[wid] = time.time() + 900
                    (deepq if kind == 'inner' else ringq if kind == 'ring' else city.queue).append(wid)
                    log.warning('ROUND3_BLOCKED kind=%s way=%s until=%.0f', kind, wid, portal_gate.cooldown_until())
                except Exception as exc:
                    state['errors'] += 1
                    deferred[wid] = time.time() + 60
                    (deepq if kind == 'inner' else ringq if kind == 'ring' else city.queue).append(wid)
                    log.warning('ROUND3_RETRY kind=%s error=%s', kind, type(exc).__name__)
            # One cache-only pass per changed HTTP/cache-miss count, not an endless spin.
            if not pending and cooldown > time.time() and last_offline != lookup.stats['requests']:
                candidates = [('inner', wid) for wid in deepq] + [('ring', wid) for wid in ringq]
                # Scan a bounded round-robin city batch during locks too.
                for _ in range(batch):
                    wid = city.next()
                    if wid:
                        candidates.append(('city', wid))
                for kind, wid in candidates:
                    if stop.is_set(): break
                    try:
                        result, cuts, partial = measure(kind, wid, True)
                    except parcels.Unavailable:
                        if kind == 'city': city.queue.append(wid)
                        continue
                    if partial is not None:
                        partials[wid] = partial
                        continue
                    partials.pop(wid, None)
                    accept(kind, wid, result, cuts, True)
                    if kind != 'city': (deepq if kind == 'inner' else ringq).remove(wid)
                last_offline = lookup.stats['requests']
                log.info('ROUND3_OFFLINE completed=%s portal_requests=0', state.get('round3_completed'))
            if ready or time.time() - last_report >= 30:
                with guard:
                    update(state, cache, inner, ring)
                    state['cooldown_until'] = datetime.fromtimestamp(portal_gate.cooldown_until(), campus_priority.VN).isoformat()
                    save()
                if time.time() - last_report >= 30:
                    log.info('ROUND3_PROGRESS completed=%s point_cache=%s interval_s=%.2f', state.get('round3_completed'), dict(lookup.stats), portal_gate.request_interval())
                    last_report = time.time()
            if not pending and not deepq and not ringq and city.finished:
                break
            if not pending: stop.wait(1)
    update(state, cache, inner, ring)
    save()
