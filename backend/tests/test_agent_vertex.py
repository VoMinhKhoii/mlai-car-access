"""Offline Vertex routing, signed history, and shared daily-quota regressions."""
import copy
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from app import agent, agent_budget, ai


DAILY = {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'details': [
    {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [
        {'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
         'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}
BODY = {'contents': [], 'generationConfig': {'maxOutputTokens': 32}}
REPLY = {'candidates': [{'finishReason': 'STOP', 'content': {
    'role': 'model', 'parts': [{'text': 'Đã kiểm tra.'}]}}]}


class VertexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for mock in (
            patch.object(agent_budget, 'STORE', Path(temp.name)),
            patch.object(agent_budget, 'FILE', Path(temp.name) / 'ledger.json'),
            patch.object(agent, '_key_cooldowns', {}),
            patch.object(agent, '_preferred_free_key', None),
            patch.dict(os.environ, {'AGENT_ALLOW_PAID': '1', 'AGENT_FREE_CALL_LIMIT': '0',
                                   'AGENT_PAID_CALL_LIMIT': '0',
                                   'AGENT_PAID_LIMIT_USD': '3', 'AGENT_PAID_ENDPOINT': '',
                                   'PROD_GEMINI_API_KEY': 'fake-paid'}),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def test_paid_vertex_default_and_override_free_stays_ai_studio(self):
        usage = {'promptTokenCount': 10, 'candidatesTokenCount': 5, 'thoughtsTokenCount': 7}
        for override in ('', 'https://vertex.example/v1/models/custom:generateContent'):
            with self.subTest(override=override), patch.dict(os.environ, {'AGENT_PAID_ENDPOINT': override}), \
                 patch.object(ai, 'gemini_keys', return_value=['fake-free']), \
                 patch.object(agent.httpx, 'post', side_effect=[httpx.Response(503),
                     httpx.Response(200, json={**REPLY, 'usageMetadata': usage})]) as post:
                agent._key_cooldowns.clear()
                agent.generate(copy.deepcopy(BODY), True)
                free, paid = post.call_args_list
                self.assertTrue(free.args[0].startswith('https://generativelanguage.googleapis.com/'))
                self.assertEqual(paid.args[0], override or
                    'https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.5-flash:generateContent')
                self.assertEqual(paid.kwargs['json']['generationConfig']['maxOutputTokens'],
                                 agent_budget.AGENT_OUTPUT_TOKENS)
                self.assertEqual(BODY['generationConfig']['maxOutputTokens'], 32)
                self.assertEqual(free.kwargs['headers']['x-goog-api-key'], 'fake-free')
                self.assertEqual(paid.kwargs['headers']['x-goog-api-key'], 'fake-paid')
        report = agent_budget.report()
        self.assertAlmostEqual(report['spent_usd'], 2 * (10 * 1.5 + 12 * 9) / 1e6)
        self.assertEqual(report['thought_tokens'], 14)
        self.assertEqual(report['reservations'], {})

    def test_daily_quota_stops_other_eleven_keys_and_goes_direct_paid_next_call(self):
        with patch.object(ai, 'gemini_keys', return_value=[f'fake-free-{i}' for i in range(12)]), \
             patch.object(agent.httpx, 'post', side_effect=[httpx.Response(429, json=DAILY),
                 httpx.Response(200, json={**REPLY, 'usageMetadata': {}}),
                 httpx.Response(200, json={**REPLY, 'usageMetadata': {}})]) as post:
            agent.generate(copy.deepcopy(BODY), True)
            agent.generate(copy.deepcopy(BODY), True)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(agent_budget.report()['free_calls'], 1)
        self.assertFalse(agent_budget.free_project_available())
        self.assertTrue(all('aiplatform.googleapis.com' in call.args[0] for call in post.call_args_list[1:]))

    def test_daily_quota_paid_off_uses_conservative_fallback(self):
        with patch.dict(os.environ, {'AGENT_ALLOW_PAID': '0'}), \
             patch.object(ai, 'gemini_keys', return_value=['fake-free-a', 'fake-free-b']), \
             patch.object(agent.httpx, 'post', return_value=httpx.Response(429, json=DAILY)) as post:
            events = list(agent.events(agent.AgentRequest(message='asdfgh ???')))
            list(agent.events(agent.AgentRequest(message='asdfgh ???')))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(events[-1]['type'], 'done')
        self.assertTrue(any(event['type'] == 'answer' for event in events))
        self.assertEqual(agent_budget.report()['paid_calls'], 0)

    def test_free_ceiling_still_allows_paid(self):
        with patch.dict(os.environ, {'AGENT_FREE_CALL_LIMIT': '1'}):
            agent_budget.free_call()
            with patch.object(ai, 'gemini_keys', return_value=['fake-free']), \
                 patch.object(agent.httpx, 'post', return_value=httpx.Response(200, json={**REPLY, 'usageMetadata': {}})) as post:
                agent.generate(copy.deepcopy(BODY), True)
        self.assertEqual(post.call_count, 1)
        self.assertIn('aiplatform.googleapis.com', post.call_args.args[0])

    def test_pacific_midnight_persists_and_expires_across_dst(self):
        for now, reset in (
            ('2026-10-17T04:00:00+00:00', '2026-10-17T07:00:00+00:00'),
            ('2026-11-01T07:30:00+00:00', '2026-11-02T08:00:00+00:00'),
            ('2026-03-08T08:30:00+00:00', '2026-03-09T07:00:00+00:00'),
        ):
            with self.subTest(now=now):
                agent_budget.cool_down_free_project(datetime.fromisoformat(now))
                self.assertEqual(agent_budget.report()['free_project_cooldown_until'],
                                 datetime.fromisoformat(reset).timestamp())
                with patch.object(agent_budget, 'datetime') as clock:
                    clock.now.return_value = datetime.fromisoformat(reset)
                    self.assertTrue(agent_budget.free_project_available())
                    agent_budget.free_call()
                    clock.now.return_value = datetime.fromtimestamp(
                        datetime.fromisoformat(reset).timestamp() - 1, timezone.utc)
                    self.assertFalse(agent_budget.free_project_available())
                    with self.assertRaises(ValueError):
                        agent_budget.free_call()

    def test_daily_detection_does_not_treat_transient_or_invalid_key_as_daily(self):
        for text in ('quota exceeded: requests per minute', 'RESOURCE_EXHAUSTED',
                     'API_KEY_SERVICE_BLOCKED', 'unavailable'):
            self.assertFalse(agent_budget.daily_quota_error(429, text))
        self.assertTrue(agent_budget.daily_quota_error(429, 'Quota exceeded: requests_per_day'))
        self.assertTrue(agent_budget.daily_quota_error(403, 'daily quota exceeded'))
        self.assertFalse(agent_budget.daily_quota_error(200, str(DAILY)))

    def test_generic_ai_rotation_obeys_same_project_cooldown(self):
        with patch.object(ai, 'provider', return_value=('gemini', 'gemini-2.5-flash')), \
             patch.object(ai, 'gemini_keys', return_value=['fake-free-a', 'fake-free-b']), \
             patch.object(ai.httpx, 'post', return_value=httpx.Response(429, json=DAILY)) as post:
            with self.assertRaises(ai.NoModel):
                ai._call('test')
            with self.assertRaises(ai.NoModel):
                ai._call('test')
        self.assertEqual(post.call_count, 1)

    def test_vertex_signed_function_parts_roundtrip_across_http_and_turns(self):
        signed = {'role': 'model', 'parts': [{'functionCall': {'name': 'tim_dia_diem',
                  'args': {'query': 'hẻm'}, 'id': 'call-1'}, 'thoughtSignature': 'fake-signature'}]}
        reply = {'role': 'model', 'parts': [{'text': 'Xin xác nhận địa chỉ.'}]}
        sent = []
        def post(url, **kwargs):
            self.assertIn('aiplatform.googleapis.com', url)
            sent.append(copy.deepcopy(kwargs['json']))
            return httpx.Response(200, json={'usageMetadata': {'thoughtsTokenCount': 2},
                'candidates': [{'content': copy.deepcopy(signed if len(sent) == 1 else reply)}]})
        with patch.object(ai, 'gemini_keys', return_value=[]), \
             patch.object(agent.httpx, 'post', side_effect=post), \
             patch.object(agent, 'execute', return_value=({'results': []}, None)):
            events = list(agent.events(agent.AgentRequest(message='Tới hẻm')))
            history = events[-1]['contents']
            list(agent.events(agent.AgentRequest(message='Còn VF 3?', contents=history)))
        self.assertEqual(sent[1]['contents'][1], signed)
        self.assertEqual(sent[2]['contents'][1], signed)
        self.assertEqual(sent[1]['contents'][2]['parts'][0]['functionResponse']['id'], 'call-1')

    def test_paid_thinking_only_retry_charges_actual_usage_and_preserves_signature(self):
        usage = {'promptTokenCount': 100, 'thoughtsTokenCount': 241, 'totalTokenCount': 341}
        empty = {'candidates': [{'finishReason': 'MAX_TOKENS'}], 'usageMetadata': usage}
        signed = {'role': 'model', 'parts': [{'functionCall': {'name': 'tim_dia_diem',
                  'args': {'query': 'hẻm'}}, 'thoughtSignature': 'exact-signature'}]}
        success = {'candidates': [{'finishReason': 'STOP', 'content': signed}],
                   'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 27,
                                     'thoughtsTokenCount': 120}}
        with patch.object(ai, 'gemini_keys', return_value=[]), \
             patch.object(agent.httpx, 'post', side_effect=[httpx.Response(200, json=empty),
                 httpx.Response(200, json=success)]) as post:
            self.assertEqual(agent.generate(BODY, True)['candidates'][0]['content'], signed)
        self.assertEqual([c.kwargs['json']['generationConfig']['maxOutputTokens']
                          for c in post.call_args_list], [2048, 4096])
        report = agent_budget.report()
        self.assertEqual(report['paid_calls'], 2)
        self.assertEqual(report['prompt_tokens'], 200)
        self.assertEqual(report['thought_tokens'], 361)
        self.assertEqual(report['output_tokens'], 388)
        self.assertAlmostEqual(report['spent_usd'], (200 * 1.5 + 388 * 9) / 1e6)
        self.assertEqual(report['recent_paid_usage'][0]['usageMetadata'], usage)
        self.assertEqual(report['reservations'], {})

    def test_empty_or_truncated_free_and_paid_retry_once_then_clear_error(self):
        for paid in (False, True):
            for candidate in ({'finishReason': 'MAX_TOKENS'}, {},
                              {'content': {'parts': []}},
                              {'finishReason': 'MAX_TOKENS', 'content': REPLY['candidates'][0]['content']}):
                with self.subTest(paid=paid, candidate=candidate), \
                     patch.object(ai, 'gemini_keys', return_value=[] if paid else ['fake-free']), \
                     patch.object(agent.httpx, 'post', return_value=httpx.Response(200, json={
                         'candidates': [candidate], 'usageMetadata': {'thoughtsTokenCount': 241}})) as post:
                    with self.assertRaisesRegex(ValueError, 'sau khi tự thử lại'):
                        agent.generate({'generationConfig': {'maxOutputTokens': 4096}}, paid)
                    self.assertEqual(post.call_count, 2)
                    self.assertEqual([c.kwargs['json']['generationConfig']['maxOutputTokens']
                                      for c in post.call_args_list], [4096, 8192])
        report = agent_budget.report()
        self.assertEqual(report['free_thought_tokens'], 8 * 241)
        self.assertEqual(report['thought_tokens'], 8 * 241)
        self.assertAlmostEqual(report['spent_usd'], 8 * 241 * 9 / 1e6)
        self.assertEqual(report['reservations'], {})

    def test_generic_ai_studio_empty_retry_and_ceiling(self):
        for success in (True, False):
            empty = {'candidates': [{'finishReason': 'MAX_TOKENS'}],
                     'usageMetadata': {'thoughtsTokenCount': 241}}
            reply = {'candidates': [{'content': {'parts': [{'text': '{"items": []}'}]}}],
                     'usageMetadata': {'candidatesTokenCount': 8}}
            with self.subTest(success=success), \
                 patch.object(ai, 'provider', return_value=('gemini', 'gemini-3.5-flash')), \
                 patch.object(ai, 'gemini_keys', return_value=['fake-free']), \
                 patch.object(ai.httpx, 'post', side_effect=[httpx.Response(200, json=empty, request=httpx.Request('POST', 'https://example.test')),
                     httpx.Response(200, json=reply if success else empty,
                                    request=httpx.Request('POST', 'https://example.test'))]) as post:
                if success:
                    self.assertEqual(ai._call('test'), {'items': []})
                else:
                    with self.assertRaisesRegex(ValueError, 'sau khi tự thử lại'):
                        ai._call('test')
                self.assertEqual([c.kwargs['json']['generationConfig']['maxOutputTokens']
                                  for c in post.call_args_list], [2048, 4096])
        self.assertEqual(agent_budget.report()['free_thought_tokens'], 3 * 241)
        sent = []
        ai.gemini_generate(lambda b: sent.append(copy.deepcopy(b)) or REPLY,
                           {'generationConfig': {'maxOutputTokens': 16000}})
        self.assertEqual(sent[0]['generationConfig']['maxOutputTokens'], 8192)

    def test_retry_error_reaches_api_without_fallback(self):
        with patch.object(ai, 'gemini_keys', return_value=[]), \
             patch.object(agent.httpx, 'post', return_value=httpx.Response(200, json={
                 'candidates': [{'finishReason': 'MAX_TOKENS'}],
                 'usageMetadata': {'thoughtsTokenCount': 241}})) as post, \
             patch.object(agent, 'fallback_events') as fallback:
            events = list(agent.events(agent.AgentRequest(message='Tới hẻm')))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('sau khi tự thử lại', events[-1]['text'])
        self.assertEqual(post.call_count, 2)
        fallback.assert_not_called()

    def test_missing_candidates_retry_at_maximum_and_reservation_floor(self):
        sent = []
        def request(body):
            sent.append(copy.deepcopy(body))
            return {'candidates': []}
        with self.assertRaisesRegex(ValueError, 'sau khi tự thử lại'):
            ai.gemini_generate(request, {'generationConfig': {'maxOutputTokens': 8192}})
        self.assertEqual([b['generationConfig']['maxOutputTokens'] for b in sent], [8192, 8192])
        rid = agent_budget.reserve(BODY)
        self.assertGreater(agent_budget.report()['reserved_usd'],
                           agent_budget.AGENT_OUTPUT_TOKENS * agent_budget.OUTPUT_USD_PER_M / 1e6)
        agent_budget.finish(rid, {'thoughtsTokenCount': 241})
        self.assertAlmostEqual(agent_budget.report()['spent_usd'], 241 * 9 / 1e6)
        self.assertEqual(agent_budget.report()['reservations'], {})

    def test_paid_attempt_limit_includes_automatic_retry(self):
        with patch.dict(os.environ, {'AGENT_PAID_CALL_LIMIT': '1'}), \
             patch.object(ai, 'gemini_keys', return_value=[]), \
             patch.object(agent.httpx, 'post', return_value=httpx.Response(200, json={
                 'candidates': [{'finishReason': 'MAX_TOKENS'}],
                 'usageMetadata': {'thoughtsTokenCount': 241}})) as post:
            with self.assertRaisesRegex(ValueError, 'hạn mức lượt Gemini trả phí'):
                agent.generate(BODY, True)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(agent_budget.report()['reservations'], {})


if __name__ == '__main__':
    unittest.main()
