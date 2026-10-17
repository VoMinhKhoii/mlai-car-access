"""Bounded identified downloader for the reviewed public bulk source manifest.

python3 pipelines/official_bulk_fetch.py
No credentials, token extraction, proxies, portal point calls, concurrency or automatic retries.
Successful cached bodies are immutable; refusals persist for manual review.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/official_bulk'
MANIFEST=ROOT/'data/official/official-bulk-downloads.json'
UA='NgoNgach-OpenDataResearch/1.0 (HCMC alley access research; contact pkhoa1331@gmail.com; bounded public bulk downloads)'


class Downloader:
    def __init__(self):
        self.last=0
        self.client=httpx.Client(headers={'User-Agent':UA},timeout=30,follow_redirects=False,trust_env=False)
        RAW.mkdir(parents=True,exist_ok=True)

    def request(self,url,label):
        body_path=RAW/(label+'.body');meta_path=RAW/(label+'.meta.json')
        if meta_path.exists():
            return json.loads(meta_path.read_text()),body_path.read_bytes() if body_path.exists() else b''
        time.sleep(max(0,2-(time.monotonic()-self.last)));self.last=time.monotonic()
        meta={'url':url,'retrieved_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'user_agent':UA}
        try:
            r=self.client.get(url);body=r.content
            meta.update(status=r.status_code,content_type=r.headers.get('content-type'),last_modified=r.headers.get('last-modified'),
                        location=r.headers.get('location'),bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
            if 'application/json' in (meta['content_type'] or ''):
                try:
                    obj=r.json()
                    if isinstance(obj,dict):
                        status=obj.get('statusCode')
                        if not status and isinstance(obj.get('error'),dict):
                            status=obj['error'].get('code')
                        if status in (401,403,429):meta['application_status']=status
                except ValueError:pass
        except httpx.HTTPError as exc:
            meta.update(status='transport_error',error=type(exc).__name__);body=b''
        body_path.write_bytes(body);meta_path.write_text(json.dumps(meta,indent=2))
        return meta,body

    def get(self,url,label):
        parsed=urlparse(url);host=parsed.netloc
        if parsed.scheme!='https' or parsed.username or parsed.password:
            raise ValueError('Only reviewed HTTPS public downloads are permitted')
        blocked=RAW/(host.replace(':','_')+'.blocked')
        if blocked.exists():return {'url':url,'status':'host_stopped_after_refusal'},b''
        meta,body=self.request(parsed.scheme+'://'+host+'/robots.txt',parsed.scheme+'_'+host.replace(':','_')+'_robots')
        if meta['status'] in (401,403,429) or meta.get('application_status') in (401,403,429):
            blocked.write_text(str(meta.get('application_status') or meta['status']))
            return {'url':url,'status':'robots_refused'},b''
        if meta['status'] not in (200,404,410):return {'url':url,'status':'robots_unavailable'},b''
        robots=RobotFileParser();robots.parse(body.decode(errors='replace').splitlines())
        if meta['status']==200:
            if 'text/html' in (meta.get('content_type') or ''):return {'url':url,'status':'robots_invalid_html'},b''
            if not robots.can_fetch(UA,url):return {'url':url,'status':'robots_disallowed'},b''
            delay=robots.crawl_delay(UA) or robots.crawl_delay('*') or 0
            if delay:time.sleep(delay)
        meta,body=self.request(url,label)
        if meta['status'] in (401,403,429) or meta.get('application_status') in (401,403,429):
            blocked.write_text(str(meta.get('application_status') or meta['status']))
        return meta,body


if __name__=='__main__':
    downloader=Downloader()
    try:
        for item in json.loads(MANIFEST.read_text())['downloads']:
            if urlparse(item['url']).hostname not in {'maps.hcmgis.vn','thuduc-maps.hcmgis.vn','congbao.hochiminhcity.gov.vn'}:
                raise ValueError('Manifest contains an unreviewed host')
            meta,_=downloader.get(item['url'],item['cache_label'])
            print(json.dumps(meta,ensure_ascii=False))
    finally:downloader.client.close()
