"""Offline regressions for the demo location and official October tide boundary."""
import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import agent, flood, main, plan, vehicles


class AgentRoundTwoTests(unittest.TestCase):
    def test_curated_house_end_wins_without_search(self):
        with patch.object(main, 'search') as search, patch.object(main, '_way_mid') as midpoint, \
                patch.object(agent.httpx, 'get', side_effect=AssertionError('Curated places must stay offline')):
            found, _ = agent.execute('tim_dia_diem', {'query': 'Hem 113/4 Vo Duy Ninh, Binh Thanh'})
        self.assertEqual(found['results'][0]['lat'], 10.792106)
        self.assertEqual(found['results'][0]['lon'], 106.716661)
        search.assert_not_called()
        midpoint.assert_not_called()

    def test_official_extrema_and_no_extrapolation(self):
        meta = flood.tide_meta()
        self.assertIn('289/2026', meta['bulletin'])
        for row in meta['highs'] + meta['lows']:
            with self.subTest(t=row['t']):
                self.assertAlmostEqual(flood.tide_level(datetime.fromisoformat(row['t'])), row['level_m'])
        self.assertIsNone(flood.tide_level(datetime.fromisoformat('2026-10-20T18:01:00+07:00')))
        self.assertIsNone(flood.tide_level(datetime.fromisoformat('2026-10-14T23:59:00+07:00')))

    def test_october17_no_false_flood_deadline(self):
        start = datetime.fromisoformat('2026-10-17T00:00:00+07:00')
        series = flood.tide_series(start, 24)
        peak = max(series, key=lambda x: x['level_m'])
        self.assertEqual(peak['level_m'], 1.20)
        self.assertEqual(peak['t'][11:16], '22:00')
        self.assertTrue(all(flood.alarm_label(s['level_m']) is None for s in series))
        vehicle = vehicles.get_profile('toyota-vios')
        for minute in range(0, 24 * 60, 15):
            arrive = start + timedelta(minutes=minute)
            self.assertIsNone(flood.FloodSnapshot([]).assess(None, arrive, vehicle.safe_water_depth).depth)

    def test_reuse_successful_free_key_between_tool_rounds(self):
        import httpx
        reply = {"candidates": [{"content": {"parts": [{"text": "Đã kiểm tra."}]}}]}
        with patch.object(agent, '_preferred_free_key', None), \
             patch.object(agent.ai, 'gemini_keys', return_value=['quota-test', 'working-test']), \
             patch.object(agent.agent_budget, 'free_call'), \
             patch.object(agent.httpx, 'post', side_effect=[httpx.Response(429),
                 httpx.Response(200, json=reply), httpx.Response(200, json=reply)]) as post:
            agent.generate({}, allow_paid=False)
            agent.generate({}, allow_paid=False)
            self.assertEqual(post.call_count, 3)
            self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'working-test')

    def test_deadline_survives_model_omission_and_followup(self):
        call = {'role': 'model', 'parts': [{'functionCall': {'name': 'lap_ke_hoach', 'args': {}}}]}
        reply = {'role': 'model', 'parts': [{'text': 'Đỗ gần đó theo bản đồ địa chính.'}]}
        result = {'verdict': {'headline': 'Đỗ gần đó'}, 'timing': {'leave_before': '17:45'}}
        with patch.object(agent, 'generate', side_effect=[{'candidates': [{'content': copy.deepcopy(call)}]},
                                                         {'candidates': [{'content': copy.deepcopy(reply)}]}]), \
             patch.object(agent, 'execute', return_value=(result, None)):
            events = list(agent.events(agent.AgentRequest(message='Đỗ hai tiếng')))
        answer = next(e['text'] for e in events if e['type'] == 'answer')
        self.assertIn('rời trước 17:45', answer)
        self.assertEqual(''.join(p.get('text', '') for p in events[-1]['contents'][-1]['parts']), answer)


if __name__ == '__main__':
    unittest.main()
