"""Offline field kit integration, including independent-process evidence refresh."""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app import evidence as ev, field_routes as fr, plan, osm
from app.field_server import app


class FieldKitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.csv = self.root/'measurements.csv'
        self.csv.write_text('osm_way_id,alley_name,width_m,date,measured_by,note,photo_url\n')
        self.patches = [patch.dict(os.environ, {'FIELD_TOKEN':'test-field-token'}),
                        patch.object(ev,'FIELD_FILE',self.csv),
                        patch.object(ev,'CONFIRM_FILE',self.root/'confirmations.jsonl'),
                        patch.object(fr,'PHOTO_DIR',self.root/'photos')]
        for p in self.patches: p.start()
        self.addCleanup(self.cleanup)
        self.client = TestClient(app)
        self.headers = {'Authorization':'Bearer test-field-token'}
        self.wid = 32584409
        row = fr.inventory()[str(self.wid)]
        self.lon, self.lat = row['coords'][len(row['coords'])//2]

    def cleanup(self):
        for p in reversed(self.patches): p.stop()
        ev.STORE_EVIDENCE.reload()
        plan.invalidate_evidence()
        self.tmp.cleanup()

    def payload(self, **kw):
        return {'submission_id':str(uuid4()),'way_id':self.wid,'lat':self.lat,'lon':self.lon,
                'width_m':2.4,'method':'tape','measured_by':'Đội hiện trường',
                'coverage_complete':True, **kw}

    def post(self, body):
        return self.client.post('/api/field/measure',json=body,headers=self.headers)

    def test_tokens_fail_closed_on_every_field_api_and_alias(self):
        for method,path in [('GET','/api/field/bootstrap'),('GET','/api/field/recent'),
          ('GET','/api/field/queue'),('GET','/api/evidence/queue'),('GET','/api/field/snap?lat=10.8&lon=106.71'),
          ('POST','/api/field/measure'),('POST','/api/field/confirm'),('POST','/api/confirm'),
          ('GET','/api/field/photos/'+str(uuid4())+'.jpg')]:
            with self.subTest(path=path): self.assertEqual(self.client.request(method,path,json={}).status_code,401)
        with patch.dict(os.environ, {'FIELD_TOKEN':''}):
            self.assertEqual(self.client.get('/api/field/recent',headers=self.headers).status_code,503)

    def test_invalid_measurements_do_not_append(self):
        for update in [{'width_m':.49},{'width_m':15.01},{'method':'estimate'}, {'lat':21.03},
                       {'way_id':99999999999999},{'lat':10.5,'lon':106.5},
                       {'measured_by':'  '},{'submission_id':'no'}, {'turn_width_m':-.5},
                       {'measured_at':'2099-01-01T00:00:00Z'},{'measured_at':'2026-10-17T00:00:00'}]:
            with self.subTest(update=update): self.assertEqual(self.post(self.payload(**update)).status_code,422)
        for value in ('NaN','Infinity'):
            raw = json.dumps(self.payload()).replace('2.4',value)
            self.assertEqual(self.client.post('/api/field/measure',content=raw,headers=self.headers).status_code,422)
        self.assertEqual(fr.rows()[1],[])

    def test_csv_metadata_and_idempotent_retry_hot_reload(self):
        before = ev.STORE_EVIDENCE.version
        p = self.payload(method='lidar',measured_at='2026-10-16T12:00:00+07:00',position_note='chỗ hẹp nhất',obstructions=['steps'],
                         turn_space='yes',turn_width_m=5,turn_length_m=7)
        r = self.post(p)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['tier'],'Measured')
        self.assertGreater(ev.STORE_EVIDENCE.version,before)
        self.assertTrue(r.json()['created'])
        self.assertFalse(self.post(p).json()['created'])
        items = self.client.get('/api/field/recent',headers=self.headers).json()['items']
        self.assertEqual(len(items),1)
        for key in ('date','source','measured_by','method','photo_url','position_note','turn_length_m'):
            self.assertIn(key,items[0])
        self.assertEqual(items[0]['method'],'lidar')
        self.assertEqual(items[0]['date'],'2026-10-16T12:00:00+07:00')
        self.assertNotEqual(items[0]['date'],items[0]['recorded_at'])
        b = next(b for b in ev.STORE_EVIDENCE.by_way[self.wid] if b.measurement_schema=='field-clear-width-v1')
        self.assertAlmostEqual(b.lo,2.3); self.assertAlmostEqual(b.hi,2.5)

    def test_pacing_is_observed_and_point_sample_not_whole_way_guarantee(self):
        self.assertEqual(self.post(self.payload(method='pacing',coverage_complete=False)).status_code,200)
        b = next(b for b in ev.STORE_EVIDENCE.by_way[self.wid] if b.measurement_schema=='field-clear-width-v1')
        self.assertEqual(b.tier,'Observed'); self.assertEqual(b.lo,0)
        self.assertAlmostEqual(b.hi,2.9); self.assertFalse(b.coverage_complete)
        self.post(self.payload(method='tape',coverage_complete=False))
        b = [b for b in ev.STORE_EVIDENCE.by_way[self.wid] if b.measurement_schema=='field-clear-width-v1'][-1]
        self.assertEqual(b.tier,'Measured'); self.assertEqual(b.lo,0)

    def test_legacy_schema_and_extra_columns_survive_upgrade(self):
        self.csv.write_text('osm_way_id,alley_name,width_m,date,measured_by,note,photo_url,custom\n32584409,,3,2026-10-16,A,,,keep\n')
        self.post(self.payload())
        fields, records = fr.rows()
        self.assertEqual(fields[:7],fr.COLUMNS[:7]); self.assertEqual(records[0]['custom'],'keep')
        bounds = ev.STORE_EVIDENCE.by_way[self.wid]
        self.assertTrue(any(b.lo==2.9 and b.coverage_complete for b in bounds))

    def test_concurrent_atomic_appends_do_not_lose_rows(self):
        def write(i):
            return fr.atomic_csv({'submission_id':str(uuid4()),'osm_way_id':self.wid,'width_m':2.4,'method':'tape','note':str(i)})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write,range(24)))
        fields, records = fr.rows()
        self.assertEqual(len(records),24); self.assertEqual(len({r['note'] for r in records}),24)
        self.assertTrue(all(set(r)==set(fields) for r in records))

    def test_photo_bytes_and_exif_are_preserved_and_require_token(self):
        image = Image.new('RGB',(8,8),(120,160,180))
        exif = Image.Exif(); exif[270]='GPS-provenance-test'
        exif[34853] = {1:'N',2:(10.,48.,0.),3:'E',4:(106.,42.,0.)}
        buf = io.BytesIO(); image.save(buf,format='JPEG',exif=exif)
        raw = buf.getvalue()
        r = self.post(self.payload(photo_base64=base64.b64encode(raw).decode()))
        self.assertEqual(r.status_code,200,r.text)
        url = r.json()['recorded']['photo_url']
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.headers).content,raw)
        self.assertEqual(Image.open(io.BytesIO(raw)).getexif().get_ifd(34853)[1], 'N')
        self.assertEqual(self.post(self.payload(photo_base64=base64.b64encode(b'<svg/>').decode())).status_code,422)

    def test_arrival_reuses_existing_confirmation_evidence_and_deduplicates(self):
        p = {'submission_id':str(uuid4()),'vehicle_id':'toyota-vios','way_ids':[self.wid],
             'lat':self.lat,'lon':self.lon,'result':'in','mirrors_folded':True}
        for _ in range(2):
            r = self.client.post('/api/confirm',json=p,headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(ev.CONFIRM_FILE.read_text().splitlines()),1)
        b = next(b for b in ev.STORE_EVIDENCE.by_way[self.wid] if b.source=='Xác nhận sau khi đến')
        self.assertEqual(b.tier,'Observed')
        self.assertAlmostEqual(b.lo,r.json()['recorded']['body_width'])
        for update in ({'result':'whatever'},{'vehicle_id':'missing'},{'way_ids':[]},{'way_ids':[999999999999]}):
            self.assertEqual(self.client.post('/api/confirm',json={**p,**update},headers=self.headers).status_code,422)

    def test_field_server_has_no_paid_or_admin_surface(self):
        for path in ['/api/agent','/api/budget','/api/config','/api/flags','/api/area/build','/api/lookup/places','/api/ai/review','/api/plan','/mcp','/docs','/openapi.json','/']:
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,404,path)

    def test_gps_snap_uses_cached_way_geometry(self):
        r = self.client.get(f'/api/field/snap?lat={self.lat}&lon={self.lon}',headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertIn(self.wid,[w['way_id'] for w in r.json()['items']])

    def test_other_process_append_refreshes_already_warm_plan(self):
        # A child process appends CSV while this process already has warm width caches.
        g, before, _ = plan.area(self.lat,self.lon)
        self.assertIn(self.wid,g.ways)
        version = ev.STORE_EVIDENCE.version
        code = '''import sys; from pathlib import Path
from app import evidence as ev, field_routes as fr
ev.FIELD_FILE=Path(sys.argv[1])
fr.atomic_csv({'submission_id':sys.argv[2],'osm_way_id':sys.argv[3],'width_m':2.4,'method':'tape','coverage_complete':'true','measured_by':'child','date':'2026-10-17'})
'''
        subprocess.run([sys.executable,'-c',code,str(self.csv),str(uuid4()),str(self.wid)],check=True,env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])})
        _, after, _ = plan.area(self.lat,self.lon)
        self.assertGreater(ev.STORE_EVIDENCE.version,version)
        self.assertEqual(after[self.wid].top_tier,'Measured')
        self.assertTrue(any(b.tier=='Measured' and b.lo==2.3 for b in after[self.wid].evidence))

    def test_real_queue_measurement_appears_in_api_plan(self):
        # HTTP through the actual main app, with external connections forbidden.
        from app.main import app as main_app
        with patch('socket.socket.connect',side_effect=AssertionError('External network forbidden in field E2E')):
            queue = self.client.get('/api/evidence/queue?limit=100&bbox=106.70,10.79,106.725,10.812',headers=self.headers)
            self.assertEqual(queue.status_code,200,queue.text)
            g = osm.build_graph(10.8,106.71)
            chosen = next(r for r in queue.json()['items'] if r['way_id'] in g.ways and g.ways[r['way_id']].drivable)
            wid = chosen['way_id']
            node = g.ways[wid].nodes[len(g.ways[wid].nodes)//2]
            lat,lon = g.nodes[node]
            main = TestClient(main_app)
            request = {'lat':lat,'lon':lon,'vehicle_id':'toyota-vios','intent':'pickup','arrive_at':'2026-10-17T10:00:00+07:00'}
            before = main.post('/api/plan',json=request)
            self.assertEqual(before.status_code,200,before.text[:1000])
            saved = self.post(self.payload(way_id=wid,lat=lat,lon=lon))
            self.assertEqual(saved.status_code,200,saved.text)
            after = main.post('/api/plan',json=request)
            self.assertEqual(after.status_code,200,after.text[:1000])
            props = next(f['properties'] for f in after.json()['layers']['fit']['features'] if f['properties']['way_id']==wid)
            self.assertEqual(props['top_tier'],'Measured')
            bound = next(b for b in ev.STORE_EVIDENCE.by_way[wid] if b.tier=='Measured')
            self.assertAlmostEqual(bound.lo,2.3); self.assertAlmostEqual(bound.hi,2.5)
            report = {'synthetic_test_only':True,'storage':'temporary directory, not production measurements.csv',
                      'queue_way_id':wid,'submitted_width_m':2.4,'measurement':saved.json(),
                      'api_plan_layer':props,'measured_bound':bound.to_json(),
                      'network':'socket connections forbidden; no Gemini or portal calls'}
            (Path(__file__).resolve().parents[2]/'docs/eval/field-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__': unittest.main()
