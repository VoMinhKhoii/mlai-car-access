from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
time.sleep(61)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
 out=list(ex.map(lambda i:req(LOCAL,body={'jsonrpc':'2.0','id':i,'method':'ping'}),range(65)))
record('rate-limit-burst',{}, {'responses':out})
time.sleep(61);rpc('ping')
