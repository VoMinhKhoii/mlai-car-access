"""No network: signed history, baseline isolation, six-round cap and dollar guard."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import agent, agent_budget, geocoding


class AgentTests(unittest.TestCase):
    def setUp(self):
        for mock in (patch.object(geocoding, '_goong_keys', return_value=[]),
                     patch.object(agent, '_nominatim', return_value=[])):
            mock.start()
            self.addCleanup(mock.stop)

    def test_signed_parts_survive_followup(self):
        signed = {"role": "model", "parts": [{"functionCall": {"name": "tim_dia_diem", "args": {"query": "hẻm"}},
                                             "thoughtSignature": "signed-exactly"}]}
        reply = {"role": "model", "parts": [{"text": "Đỗ gần đó."}]}
        seen = []
        def generate(body, allow_paid):
            seen.append(copy.deepcopy(body))
            return {"candidates": [{"content": signed if len(seen) == 1 else reply}]}
        with patch.object(agent, "generate", generate), patch.object(agent, "execute", return_value=({"results": []}, None)):
            events = list(agent.events(agent.AgentRequest(message="Tới hẻm")))
        self.assertEqual(seen[1]["contents"][1], signed)
        history = events[-1]["contents"]
        with patch.object(agent, "generate", return_value={"candidates": [{"content": reply}]}) as call:
            list(agent.events(agent.AgentRequest(message="Còn VF 3?", contents=history)))
        self.assertEqual(call.call_args.args[0]["contents"][1], signed)

    def test_blind_has_no_tools_and_no_paid(self):
        reply = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Chưa rõ."}]}}]}
        with patch.object(agent, "generate", return_value=reply) as call:
            events = list(agent.events(agent.AgentRequest(message="Đỗ đâu?", tools=False)))
        self.assertNotIn("tools", call.call_args.args[0])
        self.assertFalse(call.call_args.kwargs["allow_paid"])
        self.assertEqual([e["type"] for e in events], ["answer", "done"])

    def test_six_tool_rounds(self):
        response = {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "tim_dia_diem", "args": {"query": "x"}}}]}}]}
        with patch.object(agent, "generate", return_value=response) as call, patch.object(agent, "execute", return_value=({"results": []}, None)):
            events = list(agent.events(agent.AgentRequest(message="Tìm hẻm")))
        self.assertEqual(sum(e["type"] == "tool_call" for e in events), 6)
        self.assertEqual(call.call_count, 7)
        self.assertNotIn("tools", call.call_args.args[0])
        self.assertEqual(events[-1]["type"], "error")

    def test_budget_reserves_thought_tokens_and_refuses_next_call(self):
        with tempfile.TemporaryDirectory() as d, patch.object(agent_budget, "STORE", Path(d)), patch.object(agent_budget, "FILE", Path(d) / "usage.json"):
            body = {"contents": [], "generationConfig": {"maxOutputTokens": 2048}}
            rid = agent_budget.reserve(body)
            self.assertGreater(agent_budget.report()["reserved_usd"], 0)
            agent_budget.finish(rid, {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 30})
            self.assertAlmostEqual(agent_budget.report()["spent_usd"], .0006)
            with agent_budget.ledger() as u:
                u["spent_usd"] = 2.999
            with self.assertRaisesRegex(ValueError, r"(?:3 USD|USD 3)"):
                agent_budget.reserve(body)
            self.assertEqual(agent_budget.report()["paid_calls"], 1)
            self.assertFalse(agent_budget.report()["reservations"])

    def test_free_rotation_and_paid_opt_in(self):
        import httpx
        response = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Được."}]}}]}
        replies = [httpx.Response(429), httpx.Response(403), httpx.Response(503), httpx.Response(200, json=response)]
        with patch.object(agent.ai, "gemini_keys", return_value=["a", "b", "c", "d"]), \
                patch.object(agent.httpx, "post", side_effect=replies) as post, \
                patch.object(agent.agent_budget, "free_call"):
            self.assertEqual(agent.generate({}, allow_paid=True), response)
            self.assertEqual(post.call_count, 4)
        with patch.object(agent.ai, "gemini_keys", return_value=[]), \
                patch.dict(agent.os.environ, {"AGENT_ALLOW_PAID": "0", "PROD_GEMINI_API_KEY": "test-only"}), \
                patch.object(agent.httpx, "post") as post:
            with self.assertRaisesRegex(ValueError, "Paid access is disabled"):
                agent.generate({}, allow_paid=True)
            post.assert_not_called()
        with patch.object(agent.ai, "gemini_keys", return_value=[]), \
                patch.dict(agent.os.environ, {"AGENT_ALLOW_PAID": "1", "PROD_GEMINI_API_KEY": "test-only"}), \
                patch.object(agent.httpx, "post") as post:
            with self.assertRaises(ValueError):
                agent.generate({}, allow_paid=False)
            post.assert_not_called()

    def test_tide_coverage(self):
        with patch.object(agent, "tide_series", return_value=[]):
            result, _ = agent.execute("muc_trieu", {"start": "2026-10-17T17:00:00+07:00", "hours": 48})
        self.assertIsNone(result["highest"])
        self.assertEqual(result["missing_points"], 145)


if __name__ == "__main__":
    unittest.main()
