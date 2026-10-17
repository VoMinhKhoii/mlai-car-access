"""Crowd security/privacy/moderation tests, no network or model calls."""
import base64
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from app import crowd, crowd_routes as cr, evidence as ev, field_routes as fr, osm
from app.field_server import app


class LedgerStore:
    def __init__(self): self.version=0; self.official={}; self.official_names={}; self.reload()
    def refresh_footprints(self): pass
    def reload(self):
        self.version+=1
        self.by_way={wid:list(bs) for wid,bs in self.official.items()};self.by_name=self.official_names
        crowd.load_into(self)
    def _add(self,b,wid): self.by_way.setdefault(wid,[]).append(b)
    def bounds_for(self,w): return self.by_way.get(w.id,[])+self.by_name.get(ev._norm_alley(w.name),[])
    def way_out_for(self,wid): return []


class CrowdTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        self.patches=[patch.dict(os.environ,{'FIELD_TOKEN':'crowd-test','FIELD_PUBLIC_URL':'https://example.test'}),
                      patch.object(crowd,'DB',root/'crowd.sqlite'),patch.object(crowd,'PHOTOS',root/'photos')]
        for p in self.patches:p.start()
        self.store=LedgerStore(); p=patch.object(ev,'STORE_EVIDENCE',self.store);p.start();self.patches.append(p)
        self.addCleanup(self.cleanup)
        self.wid=32584409; row=fr.inventory()[str(self.wid)]
        self.lon,self.lat=row['coords'][len(row['coords'])//2]
        self.headers={'Authorization':'Bearer crowd-test'}
        p=patch.object(fr,'inventory',return_value={str(self.wid):row});p.start();self.patches.append(p)

    def cleanup(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def client(self):
        c=TestClient(app)
        self.assertEqual(c.post('/api/crowd/session',json={}).status_code,200)
        return c

    def photo(self,seed=1):
        image=Image.new('RGB',(20,20),(seed*31%255,110,180))
        exif=Image.Exif();exif[271]='PRIVATE-MAKE';exif[270]='PRIVATE-NAME'
        exif[306]='2026:10:17 10:00:00';exif[34853]={1:'N',2:(10.,48.,0.),3:'E',4:(106.,42.,0.)}
        buf=io.BytesIO();image.save(buf,format='JPEG',exif=exif)
        return base64.b64encode(buf.getvalue()).decode()

    def payload(self,**kw):
        return {'submission_id':str(uuid4()),'way_id':self.wid,'lat':self.lat,'lon':self.lon,
                'width_m':2.4,'method':'lidar','photo_base64':self.photo(),
                'confirmed_way':True,'photo_attestation':True,**kw}

    def post(self,c,p=None,ip='network1'):
        with patch.object(cr,'ip_key',return_value=crowd.digest(ip)):
            return c.post('/api/crowd/measure',json=p or self.payload())

    def approve(self,sid,**kw):
        return TestClient(app).post('/api/field/crowd/review/'+sid,headers=self.headers,
               json={'decision':'approved','reviewer':'Teammate','note':'Ảnh rõ và đúng vị trí',**kw})

    def test_anonymous_requires_issued_cookie_but_not_login(self):
        c=TestClient(app)
        self.assertEqual(self.post(c).status_code,401)
        c.cookies.set(cr.COOKIE,'forged.invalid')
        self.assertEqual(self.post(c).status_code,401)
        c=self.client();self.assertEqual(self.post(c).status_code,200)

    def test_invalid_photo_method_range_location_and_confirmation(self):
        c=self.client()
        for kw in ({'photo_base64':''},{'photo_base64':base64.b64encode(b'not-image').decode()},
                   {'method':'pacing'},{'width_m':.79},{'width_m':12.01},{'lat':21},
                   {'way_id':999999999999},{'confirmed_way':False},{'photo_attestation':False}):
            with self.subTest(kw=kw):self.assertEqual(self.post(c,self.payload(**kw)).status_code,422)
        self.assertEqual(crowd.records(),[])

    def test_pending_is_not_evidence_and_review_is_token_protected(self):
        r=self.post(self.client());self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['status'],'pending');self.assertNotIn(self.wid,self.store.by_way)
        sid=r.json()['id'];c=TestClient(app)
        self.assertEqual(c.get('/api/field/crowd/review').status_code,401)
        self.assertEqual(c.get('/api/field/crowd/photo/'+sid).status_code,401)
        self.assertEqual(c.post('/api/field/crowd/review/'+sid,json={}).status_code,401)
        self.assertEqual(self.approve(sid).status_code,200)
        self.assertEqual(self.store.by_way[self.wid][0].tier,'Measured')
        self.assertFalse(self.store.by_way[self.wid][0].coverage_complete)

    def test_two_independent_devices_agree_and_duplicate_does_not_count(self):
        a,b=self.client(),self.client();p=self.payload()
        first=self.post(a,p,ip='net1');self.assertEqual(first.json()['status'],'pending')
        again=self.post(a,p,ip='net1');self.assertEqual(again.json()['status'],'pending')
        second=self.post(b,self.payload(width_m=2.65,photo_base64=self.photo(2)),ip='net2')
        self.assertEqual(second.json()['status'],'consensus',second.text)
        self.assertEqual(len(crowd.records()),2)
        self.assertTrue(all(r['status']=='consensus' for r in crowd.records()))
        self.assertEqual(self.store.by_way[self.wid][0].tier,'Measured')
        # Revoking one member of a pair removes the other's unreviewed acceptance.
        self.assertEqual(self.approve(first.json()['id'],decision='rejected').status_code,200)
        self.assertNotIn(self.wid,self.store.by_way)

    def test_same_device_same_ip_or_same_photo_cannot_create_consensus(self):
        a=self.client()
        self.post(a,self.payload(photo_base64=self.photo(1)),ip='net1')
        self.post(a,self.payload(photo_base64=self.photo(2)),ip='net2')
        self.assertTrue(all(r['status']=='pending' for r in crowd.records()))
        # The same-network second client can agree with a different network record from device a.
        # Test each isolation condition in a fresh ledger instead of mixing all pairs.
        con=crowd.connect();con.execute('DELETE FROM submissions');con.execute('DELETE FROM attempts');con.commit();con.close()
        self.post(a,self.payload(photo_base64=self.photo(1)),ip='net1')
        self.post(self.client(),self.payload(photo_base64=self.photo(1)),ip='net2')
        self.assertTrue(all(r['status']=='pending' for r in crowd.records()))
        con=crowd.connect();con.execute('DELETE FROM submissions');con.commit();con.close()
        self.post(a,self.payload(photo_base64=self.photo(1)),ip='net1')
        self.post(self.client(),self.payload(photo_base64=self.photo(2)),ip='net1')
        self.assertTrue(all(r['status']=='pending' for r in crowd.records()))

    def test_official_needs_explicit_review_even_after_two_devices(self):
        self.store.official={self.wid:[ev.Bound(3,3.5,'Official','Địa chính','') ]};self.store.reload()
        a=self.post(self.client(),self.payload(),ip='net1')
        b=self.post(self.client(),self.payload(photo_base64=self.photo(2)),ip='net2')
        self.assertEqual(b.json()['status'],'pending');self.assertEqual(len(self.store.by_way[self.wid]),1)
        self.assertEqual(self.approve(a.json()['id']).status_code,422)
        self.assertEqual(self.approve(a.json()['id'],official_override_ack=True).status_code,200)
        self.assertTrue(any(b.tier=='Measured' for b in self.store.by_way[self.wid]))
        # Later Official coverage also suppresses already-consensus evidence.
        con=crowd.connect();con.execute("UPDATE submissions SET status='consensus'");con.commit();con.close()
        self.store.reload();self.assertEqual(len(self.store.by_way[self.wid]),1)

    def test_official_bound_keyed_by_name_also_blocks_consensus(self):
        name=crowd.way_name(self.wid)
        self.assertTrue(name)
        self.store.official_names={ev._norm_alley(name):[ev.Bound(3,3.5,'Official','Địa chính theo tên','')]}
        self.store.reload()
        self.post(self.client(),self.payload(),ip='net1')
        r=self.post(self.client(),self.payload(photo_base64=self.photo(2)),ip='net2')
        self.assertEqual(r.json()['status'],'pending')
        self.assertEqual(self.approve(r.json()['id']).status_code,422)

    def test_disagreeing_reviewed_samples_widen_range_and_mark_review(self):
        a=self.post(self.client(),self.payload(width_m=2),ip='net1')
        b=self.post(self.client(),self.payload(width_m=4,photo_base64=self.photo(2)),ip='net2')
        self.assertEqual(b.json()['status'],'pending')
        self.approve(a.json()['id']);self.approve(b.json()['id'])
        g=osm.AreaGraph((self.lat,self.lon));g.ways[self.wid]=osm.Way(self.wid,{'highway':'service','service':'alley'},[])
        wr=ev.width_ranges(g)[self.wid]
        self.assertTrue(wr.review);self.assertEqual(wr.top_tier,'Measured')
        self.assertEqual(wr.lo,0);self.assertAlmostEqual(wr.hi,4.15)

    def test_limits_ten_per_ip_hour_and_three_per_device_way(self):
        c=self.client()
        for _ in range(3):self.assertEqual(self.post(c).status_code,200)
        self.assertEqual(self.post(c).status_code,429)
        for _ in range(7):self.assertEqual(self.post(self.client()).status_code,200)
        self.assertEqual(self.post(self.client()).status_code,429)
        # Hourly budget resets, but the per-device per-way cap is lifetime.
        with patch.object(crowd,'now',return_value=crowd.now()+timedelta(hours=2)):
            self.assertEqual(self.post(self.client()).status_code,200)
            self.assertEqual(self.post(c).status_code,429)

    def test_device_hourly_limit_across_different_ways(self):
        device=crowd.digest('same-device')
        for i in range(10):crowd.reserve(device,crowd.digest('network-'+str(i)),1000+i)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:crowd.reserve(device,crowd.digest('network-extra'),2000)
        self.assertEqual(cm.exception.status_code,429)

    def test_photo_strips_identifiers_but_retains_gps_time(self):
        r=self.post(self.client());sid=r.json()['id']
        image=TestClient(app).get('/api/field/crowd/photo/'+sid,headers=self.headers)
        exif=Image.open(io.BytesIO(image.content)).getexif()
        self.assertNotIn(270,exif);self.assertNotIn(271,exif)
        self.assertEqual(exif[306],'2026:10:17 10:00:00')
        self.assertEqual(exif.get_ifd(34853)[1],'N')

    def test_qr_url_stats_privacy_and_daily_distinct_way_count(self):
        c=self.client();a=self.post(c);self.approve(a.json()['id'])
        stats=c.get('/api/crowd/stats').json()
        self.assertEqual(stats['public_url'],'https://example.test/field?crowd=1')
        self.assertEqual(stats['measured_alleys'],1)
        self.assertEqual(set(stats['points'][0]),{'way_id','lat','lon'})
        self.assertNotIn('nickname',json.dumps(stats));self.assertNotIn('device',json.dumps(stats))
        qr=c.get('/api/crowd/qr.svg');self.assertEqual(qr.status_code,200);self.assertIn('<svg',qr.text)
        with patch.dict(os.environ,{'FIELD_PUBLIC_URL':''}):
            self.assertEqual(c.get('/api/crowd/qr.svg').status_code,503)
            self.assertIsNone(c.get('/api/crowd/stats').json()['public_url'])


if __name__=='__main__':unittest.main()
