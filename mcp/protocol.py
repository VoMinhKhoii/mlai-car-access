"""Shared dependency-free MCP JSON-RPC core, used by stdio and FastAPI.
Pinned stable protocol: https://modelcontextprotocol.io/specification/2025-11-25
Stateless, tools-only, JSON response mode; no server-initiated requests/SSE sessions.
"""
import json
import math

VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')


class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def schema_args(schema, args):
    if not isinstance(args, dict): raise RPCError(-32602, 'arguments must be an object')
    if any(k not in args for k in schema.get('required', [])):
        raise RPCError(-32602, 'Missing required tool arguments')
    props = schema.get('properties', {})
    if any(k not in props for k in args): raise RPCError(-32602, 'Unknown tool argument')
    for key, value in args.items():
        rule = props[key]; kind = rule.get('type')
        valid = {'string':isinstance(value,str), 'number':isinstance(value,(int,float)) and not isinstance(value,bool),
                 'integer':isinstance(value,int) and not isinstance(value,bool), 'boolean':isinstance(value,bool)}
        if kind in ('number','integer') and isinstance(value,(int,float)) and not math.isfinite(value): raise RPCError(-32602, 'Non-finite argument: '+key)
        if kind in valid and not valid[kind]: raise RPCError(-32602, 'Invalid argument type: '+key)
        if 'enum' in rule and value not in rule['enum']: raise RPCError(-32602, 'Invalid argument value: '+key)
        if 'maximum' in rule and value > rule['maximum']: raise RPCError(-32602, 'Argument exceeds maximum: '+key)


def dispatch(req, list_tools, call_tool):
    if not isinstance(req,dict) or req.get('jsonrpc') != '2.0' or not isinstance(req.get('method'),str):
        return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid Request'}}
    ident=req.get('id')
    if isinstance(ident,(dict,list,bool)):
        return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request id'}}
    method=req['method'];params=req.get('params',{})
    if not isinstance(params,dict):
        return {'jsonrpc':'2.0','id':ident,'error':{'code':-32602,'message':'params must be an object'}}
    if 'id' not in req:
        return None  # Notifications must never elicit a JSON-RPC response.
    response={'jsonrpc':'2.0','id':ident}
    try:
        if method == 'initialize':
            version=params.get('protocolVersion')
            result={'protocolVersion':version if version in VERSIONS else VERSIONS[0],
                    'capabilities':{'tools':{'listChanged':False}},
                    'serverInfo':{'name':'ngo-ngach','title':'Ngõ Ngách','version':'1.0.0'},
                    'instructions':'Địa chỉ TP.HCM; giờ Asia/Ho_Chi_Minh. Answer with verdict.estimate + confidence + basis. Preserve verified/unverified_reasons; unknown exit/flood is not a pass. Restricted means prohibition + citation, never stopping advice.'}
        elif method == 'ping': result={}
        elif method == 'tools/list':
            if params.get('cursor'): raise RPCError(-32602,'Unknown cursor')
            result={'tools':list_tools()}
        elif method == 'tools/call':
            name=params.get('name');tools={t['name']:t for t in list_tools()}
            if not isinstance(name,str) or name not in tools: raise RPCError(-32602,'Unknown tool')
            args=params.get('arguments',{});schema_args(tools[name]['inputSchema'],args)
            try:
                data=call_tool(name,args)
                result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],
                        'structuredContent':data,'isError':bool(data.get('error'))}
            except Exception as exc:
                # Adapter exposes only curated ValueErrors; never leak HTTP credential URLs.
                message=str(exc) if isinstance(exc,ValueError) else 'Nguồn dữ liệu chưa sẵn sàng; hãy thử lại.'
                result={'isError':True,'content':[{'type':'text','text':message}]}
        else: raise RPCError(-32601,'Method not found')
        response['result']=result
    except RPCError as exc: response['error']={'code':exc.code,'message':exc.message}
    except Exception: response['error']={'code':-32603,'message':'Internal tool service error'}
    return response
