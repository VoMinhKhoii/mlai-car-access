import unittest
from datetime import datetime
from app import legality, osm, evidence


class LegalityKnowledgeTests(unittest.TestCase):
    def test_no_known_rule_is_not_permission(self):
        g = osm.graph_from_elements(10.8, 106.71, [
            {'type': 'node', 'id': 1, 'lat': 10.8, 'lon': 106.71},
            {'type': 'node', 'id': 2, 'lat': 10.8, 'lon': 106.711},
            {'type': 'way', 'id': 20, 'nodes': [1, 2], 'tags': {'highway': 'tertiary'}}], 'test')
        for intent in ('park', 'pickup'):
            status, rules = legality.legality_on_street(g, g.ways[20], evidence.WidthRange(8, 8.3, 'Official'),
                                                       10.8, 106.7105, 100, intent, datetime.fromisoformat('2026-10-17T12:00+07:00'))
            self.assertEqual(status, 'Unverified')
            self.assertIn('Không thấy quy định cấm đã biết', rules[-1].text)
            self.assertFalse(any(r.status == 'Permitted' for r in rules))

    def test_known_prohibition_does_not_also_claim_no_known_rule(self):
        g=osm.graph_from_elements(10.8,106.71,[
            {'type':'node','id':1,'lat':10.8,'lon':106.71},
            {'type':'node','id':2,'lat':10.8,'lon':106.711},
            {'type':'way','id':20,'nodes':[1,2],'tags':{'highway':'residential'}}],'test-known-ban')
        status,rules=legality.legality_on_street(g,g.ways[20],evidence.WidthRange(3,3.3,'Measured'),
            10.8,106.7105,100,'park',datetime.fromisoformat('2026-10-17T12:00+07:00'))
        self.assertEqual(status,'Prohibited')
        self.assertFalse(any(r.code=='no-rule' for r in rules))

    def test_customer_lot_requires_authorization(self):
        self.assertEqual(legality.legality_for_lot({'access': 'customers'}, 'park')[0], 'Unverified')
        self.assertEqual(legality.legality_for_lot({'source': 'VETC'}, 'park')[0], 'Unverified')

    def test_restricted_verdict_shows_prohibition_without_stopping_advice(self):
        from app import plan
        stop={'verified':False,'kind':'street','name':'test','walk':{'meters':20},
              'legality':{'status':'Restricted','rules':[{'status':'Restricted','text':'Không dừng, đỗ xe','citation':'test law'}]}}
        verdict=plan._verdict([stop],None,'pickup',150)
        self.assertIn('Không dừng, đỗ xe',verdict['detail'])
        self.assertNotIn('Gợi ý',verdict['detail'])

    def test_uncertain_through_route_does_not_get_a_positive_badge(self):
        from app import plan
        checks={'fit':{'class':'unknown'},'way_out':{'mode':'through','strict':False},
                'flood':{'stay':{'status':'unknown'}},'legality':{'rules':[]}}
        badges=plan._badges(checks,2,'Unverified')
        self.assertIn('Chưa xác minh đường ra',badges)
        self.assertNotIn('Đi thẳng ra',badges)
        self.assertNotIn('Không ngập',badges)


if __name__ == '__main__':
    unittest.main()
