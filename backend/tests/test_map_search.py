"""Map context and wrong-name regressions; all geocoders/model calls are mocked."""
import unittest
from unittest.mock import patch

from app import agent, geocoding as geo


class MapSearchTests(unittest.TestCase):
    def context(self, candidates=None):
        return agent.MapContext(center={'lat': 10.7605, 'lon': 106.6905}, zoom=18, candidates=candidates or [
            {'name': 'Cong Ty Cp Vuong Pham', 'lat': 10.7606, 'lon': 106.6906, 'layer': 'point_map'}])

    def test_distinctive_token_gate(self):
        for q in ('Vương Phạm', 'Cong ty CP Vuong Pham', 'CÔNG TY TNHH VƯƠNG PHẠM'):
            self.assertTrue(geo.fallback_matches(q, 'Cong Ty Cp Vuong Pham, Hẻm 115 Trần Đình Xu'))
            self.assertFalse(geo.fallback_matches(q, 'Trường Đại học Sư phạm TP.HCM, 280 An Dương Vương'))
            self.assertFalse(geo.fallback_matches(q, 'Trường Đại học Sư phạm TP.HCM'))
        self.assertFalse(geo.fallback_matches('quán công ty', 'Quán Công Ty'))
        self.assertTrue(geo.fallback_matches('alpha beta gamma delta', 'Alpha Beta Gamma'))
        self.assertFalse(geo.fallback_matches('alpha beta gamma', 'Alpha Beta'))

    def test_nominatim_lookalike_rejected_including_cached_result(self):
        wrong = [{'label': 'Trường Đại học Sư phạm TP.HCM, 280 An Dương Vương', 'lat': 10.76, 'lon': 106.68, 'source': 'Nominatim'}]
        with patch.object(geo, 'curated_search', return_value=[]), patch.object(geo, 'goong', return_value={}), patch.object(geo, 'local_search', return_value=[]), patch.object(geo, 'nominatim', return_value=wrong):
            self.assertEqual(geo.resolve_place('Vương Phạm')['results'], [])
        with patch.object(geo, '_nominatim_request', return_value=[{'display_name': wrong[0]['label'], 'lat': '10.76', 'lon': '106.68'}]):
            self.assertEqual(geo.nominatim('Vương Phạm'), [])

    def test_osm_gate_does_not_accept_partial_house_street_lookalike(self):
        with patch.object(geo, 'curated_search', return_value=[]), patch.object(geo, 'initialize_name_index', return_value=[
            {'label': 'Đường Phạm', 'norm': 'pham', 'lat': 10.76, 'lon': 106.69, 'precision': 'street'}]):
            self.assertEqual(geo.local_search('115 Vương Phạm', (10.76, 106.69)), [])

    def test_map_candidate_first_without_geocoder(self):
        with patch.object(geo, 'resolve_place', side_effect=AssertionError('must use tiles first')):
            found, _ = agent.execute('tim_dia_diem', {'query': 'Công ty CP Vương Phạm'}, None, self.context())
        self.assertEqual(found['results'][0]['label'], 'Cong Ty Cp Vuong Pham')
        self.assertEqual(found['results'][0]['source'], 'Trên bản đồ')
        self.assertFalse(found['requires_clarification'])

    def test_map_lookalike_falls_through_and_asks_for_tap(self):
        context = self.context([{'name': 'Trường Đại học Sư phạm', 'lat': 10.76, 'lon': 106.68, 'layer': 'point_map'}])
        with patch.object(geo, 'resolve_place', return_value={'results': []}) as resolve:
            result = agent.resolve_place('Vương Phạm', None, context)
        self.assertEqual(result['note'], agent.TAP_PLACE)
        self.assertEqual(resolve.call_args.args[1], (10.7605, 106.6905))

    def test_agent_request_tool_loop_passes_map_context(self):
        req = agent.AgentRequest(message='Vios tới Vương Phạm', map_context=self.context())
        call = {'role': 'model', 'parts': [{'functionCall': {'name': 'tim_dia_diem', 'args': {'query': 'Vương Phạm'}}}]}
        reply = {'role': 'model', 'parts': [{'text': 'Bạn muốn tới công ty này?'}]}
        with patch.object(agent, 'generate', side_effect=[{'candidates': [{'content': call}]}, {'candidates': [{'content': reply}]}]), patch.object(geo, 'resolve_place', side_effect=AssertionError('no external geocoder')):
            events = list(agent.events(req))
        found = next(e['result'] for e in events if e['type'] == 'tool_result')
        self.assertEqual(found['results'][0]['label'], 'Cong Ty Cp Vuong Pham')

    def test_empty_search_replaces_invented_model_answer(self):
        call = {'role': 'model', 'parts': [{'functionCall': {'name': 'tim_dia_diem', 'args': {'query': 'Vương Phạm'}}}]}
        reply = {'role': 'model', 'parts': [{'text': 'Tới trường Sư phạm nhé'}]}
        with patch.object(agent, 'generate', side_effect=[{'candidates': [{'content': call}]}, {'candidates': [{'content': reply}]}]), patch.object(agent, 'execute', return_value=({'results': []}, None)):
            events = list(agent.events(agent.AgentRequest(message='Tới Vương Phạm')))
        self.assertEqual(next(e['text'] for e in events if e['type'] == 'answer'), agent.TAP_PLACE)
        self.assertEqual(events[-1]['contents'][-1]['parts'][0]['text'], agent.TAP_PLACE)


if __name__ == '__main__':
    unittest.main()
