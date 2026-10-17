#!/usr/bin/env python3
"""Ngõ Ngách stdio → Streamable HTTP bridge; stdout is JSON-RPC only.

Forward the same dispatcher rather than maintaining a second tool catalogue or
bypassing the HTTP server's read-only checks, rate limit and authentication.
"""
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from protocol import dumps, error, loads

BASE = os.environ.get('VAODUOC_API', 'http://127.0.0.1:8787').rstrip('/')
VERSION = '2025-11-25'


def dispatch(req):
    global VERSION
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': VERSION}
    token = os.environ.get('MCP_AUTH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        request = Request(BASE + '/mcp', data=dumps(req).encode('utf-8'), headers=headers)
        with urlopen(request, timeout=45) as response:
            body = response.read()
            result = loads(body) if body else None
        if isinstance(req, dict) and req.get('method') == 'initialize' and result and 'result' in result:
            VERSION = result['result']['protocolVersion']
        return result
    except HTTPError as exc:
        try:
            response = loads(exc.read())
            if isinstance(response, dict) and response.get('jsonrpc') == '2.0':
                return response
        except (ValueError, UnicodeDecodeError):
            pass
    except Exception:
        pass
    if isinstance(req, dict) and 'id' not in req:
        return None
    return error(req.get('id') if isinstance(req, dict) else None, -32603, 'MCP HTTP service unavailable')


def main():
    # Explicit UTF-8 supports stdio clients whose locale is not Vietnamese/UTF-8.
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        try:
            req = loads(line)
        except (ValueError, UnicodeDecodeError):
            response = error(None, -32700, 'Parse error')
        else:
            response = dispatch(req)
        if response is not None:
            print(dumps(response), flush=True)


if __name__ == '__main__':
    main()
