import json, sys, subprocess
lat,lon,tag=sys.argv[1],sys.argv[2],sys.argv[3]
out=f'ttqh_{tag}.json'
subprocess.run(['curl','-s','-m','60','-A','Mozilla/5.0','-H','Referer: https://thongtinquyhoach.hochiminhcity.gov.vn/','-d',f'Lat={lat}&Lon={lon}','https://sqhkt-qlqh.tphcm.gov.vn/computing/930/api/v3.1/a-z/all','-o',out])
d=json.load(open(out,encoding='utf-8'))
t=json.loads(d['ThongTinChung']) if isinstance(d.get('ThongTinChung'),str) else d.get('ThongTinChung')
print(tag, {k:(v if len(str(v))<120 else str(v)[:60]+'...') for k,v in t.items() if k not in ('dsttdoan','ranh')})
lg=d.get('LoGioi'); lg=json.loads(lg) if isinstance(lg,str) else lg
for f in (lg or []): print('  LoGioi:', {k:v for k,v in f['properties'].items()})
vg=d.get('VatGoc'); print('  VatGoc:', str(vg)[:300])
