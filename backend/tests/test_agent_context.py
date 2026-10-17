"""AlleyAI without a model: answers to its own clarifying questions keep the earlier turns."""
import unittest
from unittest.mock import patch

from app import agent

NOW = agent.datetime(2026, 10, 17, 10, 39, tzinfo=agent.VN_TZ)


def user(text):
    return {'role': 'user', 'parts': [{'text': text}]}


def model(text):
    return {'role': 'model', 'parts': [{'text': text}]}


def ask(contents, message):
    return agent.driver_request(agent.AgentRequest(contents=contents, message=message))


class ClarificationContextTests(unittest.TestCase):
    def test_reported_conversation_keeps_destination_and_vehicle(self):
        first = ('tôi đang ở hẻm 306 Xô viết nghệ tĩnh muốn đến chợ bến thành chiều nay '
                 'thì tôi nên đi đường nào nếu trời mưa')
        args, question = ask([], first)
        self.assertEqual(question, agent.VEHICLE_Q)
        history = [user(first), model(question)]
        args, question = ask(history, 'Fortuner ấy')
        self.assertEqual(question, 'Chiều nay bạn muốn đến lúc mấy giờ?')  # not "where to?" again
        history += [user('Fortuner ấy'), model(question)]
        args, question = ask(history, '3 giờ')
        self.assertIsNone(question)
        self.assertEqual(args['vehicle_id'], 'toyota-fortuner')
        self.assertEqual(args['query'], 'chợ bến thành')
        self.assertEqual(agent.datetime.fromisoformat(args['arrive_at']).hour, 15)
        self.assertEqual(args['rain_mm_per_h'], agent.RAIN_ASSUMED_MM_H)

    def test_bare_destination_reply_and_later_vehicle(self):
        history = [user('Fortuner ấy'), model(agent.DEST_Q)]
        args, question = ask(history, 'cửa nam chợ bến thành')
        self.assertIsNone(question)
        self.assertEqual((args['vehicle_id'], args['query']), ('toyota-fortuner', 'cửa nam chợ bến thành'))

    def test_destination_given_when_asked_for_car_is_kept(self):
        history = [user('đi đâu cũng được'), model(agent.VEHICLE_Q),
                   user('cửa nam chợ bến thành'), model(agent.VEHICLE_Q)]
        args, question = ask(history, 'xe VF3')
        self.assertIsNone(question)
        self.assertEqual((args['vehicle_id'], args['query']), ('vinfast-vf-3', 'cửa nam chợ bến thành'))

    def test_latest_vehicle_wins(self):
        history = [user('Fortuner tới chợ Bến Thành chiều nay'), model('Chiều nay bạn muốn đến lúc mấy giờ?')]
        args, question = ask(history, 'à đổi sang VF3, 4 giờ chiều')
        self.assertIsNone(question)
        self.assertEqual(args['vehicle_id'], 'vinfast-vf-3')
        self.assertEqual(agent.datetime.fromisoformat(args['arrive_at']).hour, 16)

    def test_finished_answer_closes_the_gathered_request(self):
        history = [user('Fortuner tới chợ Bến Thành'), model('Chưa đủ bằng chứng để kết luận.')]
        args, question = ask(history, 'hẻm 160 Ngô Tất Tố')
        self.assertEqual(question, agent.VEHICLE_Q)  # an unrelated new question does not inherit the old car

    def test_pronoun_toi_is_not_evening(self):
        self.assertEqual(agent.parse_arrival('tôi đến lúc 8 giờ', NOW).hour, 8)
        self.assertEqual(agent.parse_arrival('tối nay 7h', NOW).hour, 19)
        self.assertEqual(agent.parse_arrival('7 giờ tối', NOW).hour, 19)


class FallbackRainNoteTests(unittest.TestCase):
    def test_assumed_rain_is_stated_and_sent_to_planner(self):
        calls = []

        def fake_execute(name, args, origin=None, map_context=None):
            calls.append((name, dict(args)))
            if name == 'tim_dia_diem':
                return {'results': [{'lat': 10.772, 'lon': 106.698, 'label': 'Chợ Bến Thành'}]}, None
            return {'request': {'rain': [{'mm_per_h': args['rain_mm_per_h']}]}, 'verdict': {'headline': 'Kết quả'}}, {}

        history = [user('Fortuner tới chợ Bến Thành nếu trời mưa'), model('Chiều nay bạn muốn đến lúc mấy giờ?')]
        req = agent.AgentRequest(contents=history, message='3 giờ chiều')
        with (patch.object(agent, 'execute', side_effect=fake_execute),
              patch.object(agent, 'grounded_answer', return_value='Kết quả.'),
              patch.object(agent, 'evidence_chips', return_value=[])):
            events = list(agent.fallback_events(req, history + [user(req.message)]))
        plan_args = next(args for name, args in calls if name == 'lap_ke_hoach')
        self.assertEqual(plan_args['rain_mm_per_h'], agent.RAIN_ASSUMED_MM_H)
        self.assertNotIn('_rain_assumed', plan_args)
        answer = next(e['text'] for e in events if e['type'] == 'answer')
        self.assertTrue(answer.startswith('Giả định trời mưa 30 mm/h'), answer)


if __name__ == '__main__':
    unittest.main()
