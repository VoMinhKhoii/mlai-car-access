"""One-shot detached night window; no crawler, lease or network until its start.

The process execs crawl_city at start, retaining PID, nice level and nohup session.
At the stop deadline the crawler saves state and exits; no daily recurrence exists.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import fcntl_compat as fcntl  # noqa: E402  (no fcntl on Windows)
DEFAULT_STATUS=ROOT/'backend/cache/live/crawl_night_schedule.json'


def atomic(path,data):
    tmp=path.with_suffix(f'.{os.getpid()}.tmp');tmp.write_text(json.dumps(data,indent=2));os.replace(tmp,path)


def wait_window(start,deadline,stop,clock=time.time,wait=None):
    """Return true only inside the explicitly authorized start/stop interval."""
    wait=stop.wait if wait is None else wait
    while not stop.is_set() and clock()<start:wait(min(30,start-clock()))
    return not stop.is_set() and start<=clock()<deadline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-at',default='2026-10-17T21:00:00+07:00')
    parser.add_argument('--stop-at',default='2026-10-18T07:00:00+07:00')
    parser.add_argument('--status',type=Path,default=DEFAULT_STATUS)
    args=parser.parse_args();start=datetime.fromisoformat(args.start_at).timestamp();deadline=datetime.fromisoformat(args.stop_at).timestamp()
    if start>=deadline:parser.error('start must precede stop')
    args.status.parent.mkdir(parents=True,exist_ok=True)
    lock=args.status.with_suffix('.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise SystemExit('Another night schedule is already waiting')
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    status={'pid':os.getpid(),'state':'waiting','start_at':args.start_at,'stop_at':args.stop_at,
            'nice':os.getpriority(os.PRIO_PROCESS,0),'recurring':False,'portal_requests_before_start':0,
            'command':['pipelines/crawl_city.py','--ranked','--portal-interval','180','--stop-at',args.stop_at]}
    atomic(args.status,status)
    print(json.dumps(status),flush=True)
    if not wait_window(start,deadline,stop):
        atomic(args.status,{**status,'state':'cancelled' if stop.is_set() else 'window_expired'})
        lock.close()
        return
    # Keep the scheduled crawler direct: no proxy or paid-provider environment.
    for key in ('PROD_GEMINI_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','AGENT_ALLOW_PAID',
                'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        os.environ.pop(key,None)
    atomic(args.status,{**status,'state':'started','started_at':datetime.now().astimezone().isoformat()})
    os.chdir(ROOT)
    os.execv(sys.executable,[sys.executable,'-u',str(ROOT/'pipelines/crawl_city.py'),'--ranked',
                             '--portal-interval','180','--stop-at',args.stop_at,'--schedule-status',str(args.status)])
    lock.close()  # exec does not return; supports injected dispatchers in offline tests


if __name__=='__main__':main()
