import json,re,math
from pathlib import Path
x=json.loads(Path('docs/qa/focused-results.json').read_text())
rows=[r for r in x['rows'] if r.get('id') and not r.get('error')]
ids={r['id']:r for r in rows}
addresses=[('Hẻm 441/14 Điện Biên Phủ','441/14 DBP'),('Hẻm 429 Điện Biên Phủ','429 DBP'),('Hẻm 479 Điện Biên Phủ','479 DBP'),('Hẻm 220/9 Xô Viết Nghệ Tĩnh','220/9 XVNT'),('Hẻm 220/9T Xô Viết Nghệ Tĩnh','220/9T branch XVNT'),('Hẻm 246 Xô Viết Nghệ Tĩnh','246 XVNT'),('Hẻm 292/13 Xô Viết Nghệ Tĩnh','292/13 XVNT'),('Hẻm 293/31 Xô Viết Nghệ Tĩnh','293/31 XVNT'),('Hẻm 356 Xô Viết Nghệ Tĩnh','356 XVNT'),('Hẻm 71 Nguyễn Văn Thương','71 Nguyễn Văn Thương')]
vids=['vinfast-vf-3','toyota-vios','toyota-fortuner']
checks=[]
for m in x['mcp']:
 r=ids.get(m['id']);p=r['plan']['data'] if r else {};q=m.get('data',{}).get('result',{}).get('structuredContent',{})
 checks.append({'id':m['id'],'ok':bool(q.get('verdict')) and p.get('verdict',{}).get('headline')==q.get('verdict',{}).get('headline') and p.get('verdict',{}).get('estimate',{}).get('answer')==q.get('verdict',{}).get('estimate',{}).get('answer') and p.get('door',{}).get('estimate',{}).get('answer')==q.get('door',{}).get('estimate',{}).get('answer')})
def cell(r):
 if not r:return 'Not completed'
 h=r['headline'].split(' — ')[0]
 if h.startswith('Tight access'):return 'Door tight'
 if h.startswith('Can reach'):return 'Door possible'
 if h.startswith('Door access unlikely'):return 'Door unlikely'
 if h.startswith('Door access unverified'):return 'Door unverified'
 if h.startswith('Access to'):return 'Nearby access unlikely'
 m=re.search(r'Park on (.*), (\d+) m walk',h)
 if m:
  name=m[1].replace('Hẻm ','').replace('Điện Biên Phủ','DBP').replace('Xô Viết Nghệ Tĩnh','XVNT')
  name=name.split(' ')[0] if name[0].isdigit() else name
  return 'Nearby'
 return h
lines=['# Ngõ Ngách live QA — HUTECH block, 17 October 2026','',f'**17/10, 14:00 UTC+7 · parking 2h · origin HUTECH 475A.** All three models: 1440×900; Vios: 390×844 (+ all three at 441/14, 429). **{len(rows)} UI checks; {sum(c["ok"] for c in checks)}/{len(checks)} MCP arrival matches** (MCP cannot accept origin).','', '**All estimates: low confidence.** Nearby = suggested parking/walk. DBP = Điện Biên Phủ; XVNT = Xô Viết Nghệ Tĩnh.','', '| Address | VF 3 | Vios | Fortuner | Suggested stop/walk | Demo-safe? |','|---|---|---|---|---|---|']
for address,label in addresses:
 rr=[next((r for r in reversed(rows)if r['address']==address and r['width']==1440 and r['vehicle']==v),None)for v in vids]
 stop=(rr[1]['plan']['data']['stop_points']or[{}])[0] if rr[1] else {}; name=stop.get('name','unknown').replace('At the door','door').replace('Hẻm ','').replace('Điện Biên Phủ','DBP').replace('Xô Viết Nghệ Tĩnh','XVNT'); name='branch'if name.startswith('Branch')else name.split(' ')[0] if name and name[0].isdigit() else name
 lines.append('| '+label+' | '+' | '.join(cell(r)for r in rr)+' | '+name+' / '+str(stop.get('walk',{}).get('meters','?'))+' m | No: B1'+('; B2'if any(r and ('unlikely' in r['headline']or'may not fit'in r['headline'])for r in rr)else '; B3'if label.startswith('356')else '')+' |')
lines+=['','**Top 5 demo blockers (repro → actual / expected):**', '', '1. **B1 — Runtime contract.** `/api/plan/compare` returns **404** for every address. All-classes row becomes width-only “Unknown”; expected full same-route answers. [Screenshot](shots/FOCUS-02-1440-toyota-vios-table.png).', '2. **B2 — Conflicting recommendation.** 429/Fortuner says “Door access unlikely” **and** “Suggested: Park at At the door.” Expected: no positive parking CTA for negative access. [Screenshot](shots/FOCUS-02-1440-toyota-fortuner.png).', '3. **B3 — Destination identity.** First 356 suggestion selects pins **102 m apart** on desktop/phone; walks **149/43 m**. Expected: canonical pins or disambiguation. [Desktop](shots/FOCUS-09-1440-toyota-vios.png), [phone](shots/FOCUS-09-390-toyota-vios.png).', '4. **B4 — Missing explanation.** 220/9/Vios omits the multi-segment width profile. Expected: every route segment, with evidence or explicit gaps. [Screenshot](shots/FOCUS-04-1440-toyota-vios-why.png).', '5. **B5 — Unsupported numeric width.** 246/Vios shows “Narrowest 3.70 m · Observed” from **motorcar permission, zero samples**. Expected: assumption label, not observed clearance. [Screenshot](shots/FOCUS-06-390-toyota-vios-why.png).', '', '**Best conditional demos:** **441/14**, all three: **0.93 m/10 cadastral cuts** → parent alley 441. **429**, VF 3/Vios: **2.90 m/one cut** → tight. Disclose incomplete coverage and B1. Avoid 429/Fortuner (B2). No clean all-feature demo yet.', '', 'No crashes, overflow, untranslated controls, code/server changes, or further AlleyAI calls. [Evidence](focused-results.json). City-wide JSON moved to `/private/tmp`.']
Path('docs/qa/e2e-qa-2026-10-17.md').write_text('\n'.join(lines)+'\n')
Path('docs/qa/parity-summary.json').write_text(json.dumps(checks,indent=2))
print('report words',len(' '.join(lines).split()),'UI',len(rows),'MCP',sum(c['ok']for c in checks),'/',len(checks))
