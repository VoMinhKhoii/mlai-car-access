#!/usr/bin/env python3
"""Ngõ Ngách MCP stdio bridge. Standard library only; stdout is JSON-RPC only."""
import json
import os
import sys
from urllib.request import Request, urlopen
from protocol import dispatch as rpc_dispatch

BASE = os.environ.get('VAODUOC_API', 'http://127.0.0.1:8787').rstrip('/')


def api(path, args=None):
    data=json.dumps(args).encode() if args is not None else None
    req=Request(BASE+path,data=data,headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=45) as response: return json.load(response)


def dispatch(req):
    return rpc_dispatch(req,lambda:api('/api/agent/tools'),lambda name,args:api('/api/agent/tool/'+name,args))


def main():
    for line in sys.stdin:
        try: req=json.loads(line)
        except ValueError:
            response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        else: response=dispatch(req)
        if response is not None: print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
