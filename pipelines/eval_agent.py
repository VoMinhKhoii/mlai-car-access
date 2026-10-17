#!/usr/bin/env python3
"""Real Gemini + real tool eval. No keys/headers are serialized. Costs share agent_budget.
Run: python3 pipelines/eval_agent.py --stage after [--limit 12]
Every case uses real Gemini and tool results. Unresolved addresses pass only as explicit clarification, and are reported separately from completed plans.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, agent_budget

# Historical urban district names remain common in driver addresses after ward mergers.
ADDRESSES = [
 ('Quận 1', '135 Nam Kỳ Khởi Nghĩa, Quận 1', 'VF3', 'vinfast-vf-3'),
 ('Quận 3', 'hẻm 12/3 Cao Thắng, Quận 3', 'Fortuner', 'toyota-fortuner'),
 ('Quận 4', '132 Bến Vân Đồn, Quận 4', 'Vios', 'toyota-vios'),
 ('Quận 5', 'bệnh viện Chợ Rẫy, Quận 5', 'xe 7 chỗ', 'class-m'),
 ('Quận 6', 'chợ Bình Tây, Quận 6', 'VF5', 'vinfast-vf-5'),
 ('Quận 7', '105 Tôn Dật Tiên, Quận 7', 'Xpander', 'mitsubishi-xpander'),
 ('Quận 8', 'hẻm 41 Phạm Thế Hiển, Quận 8', 'xe cỡ nhỏ', 'class-xs'),
 ('Quận 10', 'bệnh viện Nhi Đồng 1, Quận 10', 'Vios', 'toyota-vios'),
 ('Quận 11', 'công viên Đầm Sen, Quận 11', 'Fortuner', 'toyota-fortuner'),
 ('Quận 12', 'công viên phần mềm Quang Trung, Quận 12', 'VF3', 'vinfast-vf-3'),
 ('Bình Thạnh', 'hẻm 113/4 Võ Duy Ninh, Bình Thạnh', 'Fortuner', 'toyota-fortuner'),
 ('Bình Tân', 'bến xe Miền Tây, Bình Tân', 'VF5', 'vinfast-vf-5'),
 ('Gò Vấp', '12 Quang Trung, Gò Vấp', 'xe 7 chỗ', 'class-m'),
 ('Phú Nhuận', 'hẻm 96 Phan Đình Phùng, Phú Nhuận', 'Vios', 'toyota-vios'),
 ('Tân Bình', 'sân bay Tân Sơn Nhất, Tân Bình', 'Fortuner', 'toyota-fortuner'),
 ('Tân Phú', '30 Bờ Bao Tân Thắng, Tân Phú', 'VF3', 'vinfast-vf-3'),
 ('Thủ Đức', '1 Võ Văn Ngân, Thủ Đức', 'VF5', 'vinfast-vf-5'),
 ('Thủ Đức / Q2', 'Vincom Mega Mall Thảo Điền, Thủ Đức', 'Vios', 'toyota-vios'),
 ('Thủ Đức / Q9', 'khu công nghệ cao, Thủ Đức', 'Fortuner', 'toyota-fortuner'),
]
CASES = []
for i, (district, address, car, vid) in enumerate(ADDRESSES):
    CASES.append(dict(id=f'address-{i+1:02}', district=district,
        query=f'Tôi lái {car} tới {address}, đỗ xe 2 tiếng tối nay 7h. Vào được không?',
        expect={'vehicle_id':vid,'intent':'park','dwell_min':120,'hour':19,'geocode':True,'destination_query':address}))
    if i < 15:
        CASES.append(dict(id=f'pickup-{i+1:02}',district=district,
            query=f'{car} đón khách tại {address} sáng mai 8 giờ, dừng 10 phút.',
            expect={'vehicle_id':vid,'intent':'pickup','dwell_min':10,'hour':8,'tomorrow':True,'geocode':True,'destination_query':address}))
CASES += [
 dict(id='english', query='Can my VF3 park for 90 minutes at 65 Le Loi, District 1, HCMC tomorrow at 9am?', expect={'vehicle_id':'vinfast-vf-3','intent':'park','dwell_min':90,'hour':9,'tomorrow':True,'geocode':True}),
 dict(id='poi-ambiguous',query='Tôi đi Vios tới quán cà phê Highlands ở TP.HCM, đỗ 1 tiếng',expect={'ambiguous':True}),
 dict(id='poi-unknown',query='Tôi đi VF3 đến quán cà phê X ở TP.HCM',expect={'ambiguous':True}),
 dict(id='outside-hanoi',query='Lái Fortuner tới 1 Tràng Tiền, Hà Nội, đỗ 2 tiếng',expect={'outside':True}),
 dict(id='outside-danang',query='Đón khách ở cầu Rồng Đà Nẵng bằng VF5',expect={'outside':True}),
 dict(id='nonsense',query='asdfgh zxcvbn @@@ ???',expect={'clarify':True}),
 dict(id='no-address',query='Xe tôi có vào được không?',expect={'clarify':True}),
 dict(id='follow-car',query='Đổi sang VF3 của vợ tôi thì sao?',parent='address-11',expect={'vehicle_id':'vinfast-vf-3','intent':'park','dwell_min':120,'hour':19,'followup':True}),
 dict(id='follow-time',query='Đổi sang sáng mai lúc 8h nhé',parent='address-11',expect={'vehicle_id':'toyota-fortuner','intent':'park','dwell_min':120,'hour':8,'tomorrow':True,'followup':True}),
 dict(id='follow-nearer',query='Còn chỗ nào gần hơn?',parent='address-11',expect={'followup':True,'vehicle_id':'toyota-fortuner'}),
 dict(id='follow-rain',query='Nếu mưa 45 mm/h thì sao?',parent='address-11',expect={'followup':True,'rain':45,'vehicle_id':'toyota-fortuner'}),
 dict(id='rain',query='Vios đỗ ở hẻm 220/9 Xô Viết Nghệ Tĩnh, Bình Thạnh, tối nay 20h trong 2 tiếng, nếu mưa 30 mm/h thì sao?',expect={'vehicle_id':'toyota-vios','rain':30,'hour':20,'dwell_min':120,'intent':'park','geocode':True}),
]

def assess(case, events):
    exp=case['expect']; failures=[]
    calls=[e for e in events if e['type']=='tool_call']
    plans=[e['args'] for e in calls if e['name'] in ('lap_ke_hoach','tim_cho_do_gan')]
    errors=[e.get('text','') for e in events if e['type']=='error']
    if errors: failures.append('runtime: '+errors[-1])
    if exp.get('destination_query'):
        queries = [e['args'].get('query','') for e in calls if e['name']=='tim_dia_diem']
        expected = set(agent.strip_accents(exp['destination_query'].split(',')[0]).lower().split()) - {'hem','benh','vien','cong','vien'}
        actual = set(agent.strip_accents(' '.join(queries)).lower().replace(',', ' ').split())
        if not expected or len(expected & actual)/len(expected) < .6: failures.append('args.destination_query')
    answer=next((e.get('text','') for e in events if e['type']=='answer'),'')
    if not answer: failures.append('missing_answer')
    if events and events[-1]['type'] not in ('done','error'): failures.append('missing_terminal')
    if exp.get('outside') or exp.get('clarify'):
        if plans: failures.append('unsafe_plan_for_invalid_destination')
    elif exp.get('ambiguous'):
        if plans and not any(e.get('result',{}).get('selection_reason') for e in events):
            failures.append('ambiguous_without_clarification')
    else:
        # A geocoder with no exact house/POI match must ask, never fabricate coordinates.
        geo=[e.get('result') for e in events if e['type']=='tool_result' and e.get('name')=='tim_dia_diem' and e.get('result') is not None]
        unresolved=bool(geo and (not geo[-1].get('results') or geo[-1].get('requires_clarification')))
        if not plans and not unresolved: failures.append('missing_plan')
        if exp.get('geocode') and not any(e['name']=='tim_dia_diem' for e in calls): failures.append('missing_geocode')
        if plans:
            if not any(e['type']=='ui' for e in events): failures.append('plan_failed_or_unverified')
            a=plans[-1]
            for key in ('vehicle_id','intent','dwell_min'):
                if key in exp and a.get(key)!=exp[key]: failures.append(f'args.{key}: {a.get(key)} != {exp[key]}')
            if 'hour' in exp:
                try:
                    dt=agent.datetime.fromisoformat(a['arrive_at']).astimezone(agent.VN_TZ)
                    if dt.hour!=exp['hour']: failures.append('args.arrival_hour')
                    today=agent.datetime.now(agent.VN_TZ).date()
                    expected=today+agent.timedelta(days=bool(exp.get('tomorrow')))
                    if dt.date()!=expected: failures.append('args.arrival_day')
                except (ValueError,KeyError): failures.append('args.arrive_at')
            if 'rain' in exp and a.get('rain_mm_per_h')!=exp['rain']: failures.append('args.rain')
            if exp.get('geocode'):
                names=[e['name'] for e in calls]
                if names.index('tim_dia_diem')>names.index(next(e['name'] for e in calls if e['name'] in ('lap_ke_hoach','tim_cho_do_gan'))): failures.append('tool_order')
    violations=[e for e in events if e['type']=='validation' and e.get('violations')]
    return failures,violations


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',default='after');p.add_argument('--limit',type=int);p.add_argument('--workers',type=int,default=2)
    opts=p.parse_args();os.environ['AGENT_ALLOW_PAID']='0'
    # Hard absolute ceiling shared by subprocesses and concurrent requests; never 250 additional per run.
    os.environ.setdefault('AGENT_FREE_CALL_LIMIT','324') # baseline ledger was 74
    cases=CASES[:opts.limit] if opts.limit else CASES
    history={};rows=[];before=agent_budget.report()
    def run(case):
        t=time.monotonic()
        events=list(agent.events(agent.AgentRequest(message=case['query'],contents=history.get(case.get('parent'),[]))))
        failures,violations=assess(case,events)
        row={**case,'latency_s':round(time.monotonic()-t,3),'success':not failures,'failures':failures,'number_violations':violations,'events':events}
        done=next((e for e in events if e['type']=='done'),{})
        return row,done.get('contents',[])
    independent=[c for c in cases if not c.get('parent')]; dependent=[c for c in cases if c.get('parent')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=opts.workers) as pool:
        future={pool.submit(run,c):c for c in independent}
        for f in concurrent.futures.as_completed(future):
            row,h=f.result(); rows.append(row);history[row['id']]=h
            (ROOT/'docs/eval'/f'agent-eval-{opts.stage}-partial.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
            print(f"{row['id']}: {'PASS' if row['success'] else row['failures']} ({row['latency_s']}s)",flush=True)
    for c in dependent:
        row,h=run(c);rows.append(row);history[c['id']]=h
        print(f"{row['id']}: {'PASS' if row['success'] else row['failures']} ({row['latency_s']}s)",flush=True)
    lat=sorted(r['latency_s'] for r in rows);after=agent_budget.report()
    summary={'stage':opts.stage,'mode':'live','count':len(rows),'passed':sum(r['success'] for r in rows),'pass_rate':sum(r['success'] for r in rows)/len(rows),'latency_p50_s':statistics.median(lat),'latency_p90_s':lat[min(len(lat)-1,int(len(lat)*.9))],'free_calls':after['free_calls']-before['free_calls'],'paid_calls':after['paid_calls']-before['paid_calls'],'spent_usd':after['spent_usd']-before['spent_usd'],'fallback_cases':sum(any(e['type']=='progress' and 'AI đang bận' in e.get('text','') for e in r['events']) for r in rows)}
    path=ROOT/'docs/eval'/('agent-eval.json' if opts.stage=='after' else f'agent-eval-{opts.stage}.json')
    summary['completed_plans'] = sum(any(e['type']=='ui' for e in r['events']) for r in rows)
    summary['clarifications'] = sum(not any(e['type']=='ui' for e in r['events']) and r['success'] for r in rows)
    path.write_text(json.dumps({'summary':summary,'cases':rows},ensure_ascii=False,indent=2))
    path.with_suffix('.md').write_text('# Agent evaluation\n\n'
        + f"{summary['passed']}/{summary['count']} contract cases passed ({summary['pass_rate']:.1%}). "
        + f"{summary['completed_plans']} completed plans; {summary['clarifications']} safe clarifications/declines.\n\n"
        + f"Latency p50 {summary['latency_p50_s']:.3f}s; p90 {summary['latency_p90_s']:.3f}s. "
        + f"Fallback used in {summary['fallback_cases']} cases. This is not a destination-resolution or full-model accuracy score.\n\n"
        + f"Ledger deltas: {summary['free_calls']} free attempts, {summary['paid_calls']} paid attempts, ${summary['spent_usd']:.6f}. Concurrent processes share the ledger.\n\n"
        + 'Before/after, failure categories, quota limitations, cost and engine findings: [implementation report](agent-production-report.md).\n\n'
        + '\n'.join(f"- {r['id']}: {'PASS' if r['success'] else '; '.join(r['failures'])}" for r in rows)+'\n')
    print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
