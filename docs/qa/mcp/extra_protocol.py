from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
for name,body in [('invalid request',{'jsonrpc':'1.0','id':1,'method':'ping'}),('bad params type',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':[]}),('initialized notification',{'jsonrpc':'2.0','method':'notifications/initialized'}),('invalid extra arguments',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'list_vehicles','arguments':{'unexpected':True}}})]:
 time.sleep(1.2);record(name,{'request':body},req(LOCAL,body=body))
