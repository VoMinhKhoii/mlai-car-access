"""MCP 2025-11-25 JSON-RPC core shared by HTTP and the stdio bridge.

JSON response mode, tools only. Sessions and server-initiated streams are optional
in Streamable HTTP; this server deliberately keeps no transport session state.
"""
import json
import math
import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime

VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
HTTP_VERSIONS = VERSIONS[:3]
TOOL_ALIASES = {'tim_dia_diem': 'find_place', 'lap_ke_hoach': 'plan_arrival', 'kiem_tra_xe_vao_hem': 'check_alley_fit', 'tim_cho_do_gan': 'find_nearby_stops', 'danh_sach_xe': 'list_vehicles', 'muc_trieu': 'tide_levels'}
MAX_RESULT_BYTES = 8_000  # includes content + structuredContent + JSON-RPC envelope


class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def loads(value):
    def invalid(_):
        raise ValueError('Non-finite JSON number')
    return json.loads(value, parse_constant=invalid)


def schema_args(schema, args):
    """Validate the small, closed JSON Schema subset used by the six tools."""
    if not isinstance(args, dict):
        raise RPCError(-32602, 'arguments must be an object')
    if any(k not in args for k in schema.get('required', [])):
        raise RPCError(-32602, 'Missing required tool arguments')
    props = schema.get('properties', {})
    if any(k not in props for k in args):
        raise RPCError(-32602, 'Unknown tool argument')
    for key, value in args.items():
        rule = props[key]
        kind = rule.get('type')
        valid = {'string': isinstance(value, str),
                 'number': isinstance(value, (int, float)) and not isinstance(value, bool),
                 'integer': isinstance(value, int) and not isinstance(value, bool),
                 'boolean': isinstance(value, bool)}
        if kind in valid and not valid[kind]:
            raise RPCError(-32602, 'Invalid argument type: ' + key)
        if kind in ('number', 'integer'):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise RPCError(-32602, 'Non-finite argument: ' + key)
        if 'enum' in rule and value not in rule['enum']:
            raise RPCError(-32602, 'Invalid argument value: ' + key)
        for bound, invalid in (('minimum', lambda x: value < x), ('maximum', lambda x: value > x),
                               ('minLength', lambda x: len(value.strip()) < x),
                               ('maxLength', lambda x: len(value) > x)):
            if bound in rule and invalid(rule[bound]):
                raise RPCError(-32602, 'Argument outside ' + bound + ': ' + key)
        if rule.get('format') == 'date-time':
            try:
                if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$', value):
                    raise ValueError()
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if dt.tzinfo is None or abs(dt.utcoffset().total_seconds()) > 14 * 3600 or not 2000 <= dt.year <= 2100:
                    raise ValueError()
            except (ValueError, OverflowError):
                raise RPCError(-32602, 'Use ISO datetime with timezone (2000–2100): ' + key) from None


class RateLimiter:
    """Per-process sliding window; bounded storage, no forwarded-IP header trust."""
    def __init__(self, limit=60, window=60, max_clients=4096):
        self.limit, self.window, self.max_clients = limit, window, max_clients
        self.clients = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, client, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            # Expired entries are removed before capacity eviction.
            while self.clients and next(iter(self.clients.values()))[-1] <= now - self.window:
                self.clients.popitem(last=False)
            if client not in self.clients and len(self.clients) >= self.max_clients:
                # Refuse new identities until an entry expires; rotating identities
                # cannot evict an existing client's active quota.
                return False
            recent = self.clients.setdefault(client, deque())
            while recent and recent[0] <= now - self.window:
                recent.popleft()
            if len(recent) >= self.limit:
                return False
            recent.append(now)
            self.clients.move_to_end(client)
            return True


def dispatch(req, list_tools, call_tool):
    if not isinstance(req, dict) or req.get('jsonrpc') != '2.0':
        return error(None, -32600, 'Invalid Request')
    # Client responses are legal messages even though this tools-only server
    # never asks clients to execute anything. HTTP acknowledges them with 202.
    if 'method' not in req and 'id' in req and (('result' in req) != ('error' in req)):
        if isinstance(req['id'], bool) or not isinstance(req['id'], (str, int)):
            return error(None, -32600, 'Invalid response id')
        return None
    if not isinstance(req.get('method'), str) or 'result' in req or 'error' in req:
        return error(None, -32600, 'Invalid Request')
    ident = req.get('id')
    if 'id' in req and (isinstance(ident, bool) or not isinstance(ident, (str, int)) or isinstance(ident, str) and len(ident) > 256):
        return error(None, -32600, 'Request id must be a string or integer')
    params = req.get('params', {})
    if not isinstance(params, dict):
        return error(ident, -32602, 'params must be an object') if 'id' in req else None
    if 'id' not in req:
        return None  # including notifications/initialized and notifications/cancelled
    try:
        method = req['method']
        if method == 'initialize':
            version = params.get('protocolVersion')
            if not isinstance(version, str):
                raise RPCError(-32602, 'protocolVersion must be a string')
            result = {
                'protocolVersion': version if version in VERSIONS else VERSIONS[0],
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'ngo-ngach', 'title': 'Ngõ Ngách — alley access for vehicles in HCMC', 'version': '1.1.0'},
                'instructions': 'HCMC only; Asia/Ho_Chi_Minh. Resolve ambiguous addresses before planning. '
                'Preserve verdict.estimate, access versus legality, evidence tiers, citations and caveats. '
                'Unknown exit/flood is not a pass; Unverified legality is not permission. '
                'Read-only cached-area engine tools, no LLM or crawl. No transport sessions are issued.'}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            if params.get('cursor'):
                raise RPCError(-32602, 'Unknown cursor')
            result = {'tools': list_tools()}
        elif method == 'tools/call':
            name = params.get('name')
            if isinstance(name, str):
                name = TOOL_ALIASES.get(name, name)
            catalog = {t['name']: t for t in list_tools()}
            if not isinstance(name, str) or name not in catalog:
                raise RPCError(-32602, 'Unknown tool')
            args = params.get('arguments', {})
            schema_args(catalog[name]['inputSchema'], args)
            try:
                data = call_tool(name, args)
                if not isinstance(data, dict):
                    raise RuntimeError('Tool contract requires an object')
                failed = bool(data.get('error'))
                # A short text representation accompanies structuredContent; duplicating
                # every evidence record as JSON text would double the context budget.
                text = result_text(name, data)
                result = {'content': [{'type': 'text', 'text': str(text)}],
                          'structuredContent': data, 'isError': failed}
                if len(dumps({'jsonrpc': '2.0', 'id': ident, 'result': result}).encode()) >= MAX_RESULT_BYTES:
                    raise ValueError('Result exceeds compact response budget; request a single-alley check.')
            except Exception:
                # Never propagate provider exception strings, URLs, credentials or inputs.
                result = {'isError': True, 'content': [{'type': 'text', 'text':
                          'Tool unavailable: the source is not ready or the result exceeds the compact response budget. Please retry.'}],
                          'structuredContent': {'error': 'tool_unavailable'}}
        else:
            raise RPCError(-32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': ident, 'result': result}
    except RPCError as exc:
        return error(ident, exc.code, exc.message)
    except Exception:
        return error(ident, -32603, 'Internal tool service error')



def result_text(name, data):
    """English presentation independent of source-language labels and citations.

    Do not echo engine prose or provider errors into MCP's text content. Source
    records remain verbatim in structuredContent for traceable citations.
    """
    if data.get('error'):
        return {
            'area_not_cached': 'No cached map is available for this area. MCP will not start a build or crawl; no access conclusion is available.',
            'way_not_in_area': 'The requested alley segment is not in the cached area map.',
            'compact_result_too_large': 'The result exceeds the compact response budget. No safety conclusion is available; request a single-alley check.',
        }.get(data['error'], 'The tool is unavailable or the vehicle is not recognized. Retry or use list_vehicles.')
    if name in ('plan_arrival', 'find_nearby_stops'):
        estimate = (data.get('verdict') or {}).get('estimate') or {}
        answer = estimate.get('answer')
        confidence = estimate.get('confidence')
        answer = answer if answer in ('fits', 'tight', 'no', 'unknown') else 'unknown'
        confidence = confidence if confidence in ('high', 'medium', 'low') else 'unknown'
        return f'Arrival estimate: {answer}. Confidence: {confidence}. Physical access does not authorize stopping. Check the legal status, evidence and caveats in structuredContent.'
    if name == 'find_place':
        count = len(data.get('results') or [])
        note = ' Ask the user to select a candidate before planning.' if data.get('requires_clarification') else ''
        return f'Place search returned {count} candidate(s).{note}'
    if name == 'check_alley_fit':
        fit = data.get('fit')
        fit = fit if fit in ('fits', 'tight', 'no', 'blocked', 'unknown') else 'unknown'
        return f'Single-alley fit: {fit}. This does not certify the full route, exit, flood conditions or stopping legality.'
    if name == 'list_vehicles':
        return f'Vehicle catalogue: {len(data.get("vehicles") or [])} models and size classes. Dimensions are in metres; check assumptions and sources.'
    return 'Tide levels and source coverage are in structuredContent. Missing forecast points do not mean zero tide or no flood.'


def error(ident, code, message):
    return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': message}}
