import copy
import json
import pathlib
import random
import sys
import unittest
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from live import bundle_offers, classify, nutrition_map, prepare_snapshot
from main import demo
from meal import amount_to_fen, draw, optimize, select_best
from mcp_readonly import MCP, tool_data
from report import render


class MealTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT / 'examples' / 'demo.json').read_text(encoding='utf-8'))

    def test_default_and_no_main_across_many_draws(self):
        for seed in range(1000):
            for no_main in (False, True):
                meal = draw(self.snapshot, no_main, seed=seed)
                kinds = [i['kind'] for i in meal['items']]
                self.assertEqual(len(set(i['id'] for i in meal['items'])), 3)
                self.assertEqual('main' in kinds, not no_main)
                self.assertTrue(any(k != 'drink' for k in kinds))

    def test_random_choice_does_not_depend_on_price_or_calories(self):
        changed = copy.deepcopy(self.snapshot)
        for item in changed['items']:
            item['menu_fen'], item['kcal'] = random.randrange(99999), None
        self.assertEqual(draw(self.snapshot, seed=24)['basket'], draw(changed, seed=24)['basket'])

    def test_not_forced_to_one_main_or_a_drink(self):
        baskets = [draw(self.snapshot, seed=seed)['items'] for seed in range(100)]
        self.assertTrue(any(sum(i['kind'] == 'main' for i in b) > 1 for b in baskets))
        self.assertTrue(any(all(i['kind'] != 'drink' for i in b) for b in baskets))

    def test_missing_nutrition_is_not_complete_zero(self):
        for item in self.snapshot['items']:
            item['kcal'] = None
        result = draw(self.snapshot, seed=1)
        self.assertFalse(result['nutrition']['complete'])
        self.assertEqual(len(result['nutrition']['missing']), 3)

    def test_invalid_pool_and_live_seed_fail(self):
        self.snapshot['items'] = [i for i in self.snapshot['items'] if i['kind'] == 'drink']
        with self.assertRaises(ValueError):
            draw(self.snapshot, True)
        self.snapshot['mode'] = 'live'
        with self.assertRaises(ValueError):
            draw(self.snapshot, seed=1)

    def test_exact_basket_and_single_use_coupon(self):
        meal = draw(self.snapshot, True, seed=3)
        catalog = {**meal, 'offers': self.snapshot['offers']}
        plans = optimize(meal, catalog)
        for plan in plans['plans']:
            cover = Counter()
            for offer in plan['offers']:
                cover.update(offer['covers'])
            self.assertEqual(cover, Counter(meal['basket']))
            self.assertLessEqual(sum(o['id'].startswith('coupon:') for o in plan['offers']), 1)

    def test_complete_bundle_is_cheaper_and_extra_main_is_excluded(self):
        self.snapshot['items'] = [i for i in self.snapshot['items'] if i['id'] in ('burger', 'fries', 'cola')]
        meal = draw(self.snapshot, seed=1)
        plans = optimize(meal, {**meal, 'offers': self.snapshot['offers']})
        amounts = [sum(o['demo_fen'] for o in p['offers']) for p in plans['plans']]
        self.assertEqual(min(amounts), 2900)
        fixed = demo(seed=24)
        if fixed['comparison']['baseline_fen'] is not None:
            self.assertEqual(fixed['comparison']['savings_fen'], fixed['comparison']['baseline_fen']-fixed['comparison']['best']['payable_fen'])
        no_main = demo(True, 1)
        self.assertFalse(any('三件套' in label for q in no_main['comparison']['quotes'] for label in q['labels']))

    def test_quote_binding_failures_and_truncation(self):
        meal = draw(self.snapshot, seed=2)
        plans = optimize(meal, {**meal, 'offers': self.snapshot['offers']}, max_plans=1)
        self.assertTrue(plans['truncated'])
        comparison = select_best(meal, plans, [])
        self.assertIsNone(comparison['best'])
        self.assertEqual(len(comparison['pending']), 1)
        wrong = {'draw_id': 'old', 'mode': 'demo', 'plan_id': plans['plans'][0]['id']}
        with self.assertRaises(ValueError):
            select_best(meal, plans, [wrong])
        with self.assertRaises(ValueError):
            optimize(meal, {**meal, 'context': {'beType': 2}, 'offers': self.snapshot['offers']})
        tampered = copy.deepcopy(meal)
        tampered['items'][0]['name'] = '换了餐品但保留旧标识'
        with self.assertRaises(ValueError):
            select_best(tampered, plans, [])

    def test_amount_units_and_business_error(self):
        self.assertEqual(amount_to_fen('19.90', 'yuan'), 1990)
        self.assertEqual(amount_to_fen(1990, 'fen'), 1990)
        for value in (True, float('nan'), -1, 1.5):
            with self.assertRaises(ValueError):
                amount_to_fen(value, 'fen')
        with self.assertRaises(ValueError):
            tool_data({'structuredContent': {'success': False, 'data': {'price': 0}}})
        self.assertEqual(tool_data({'content': [{'type': 'text', 'text': '说明\n{"success":true,"data":{"price":99}}'}]})['data']['price'], 99)

    def test_bridge_blocks_mutation_before_network(self):
        bridge = object.__new__(MCP)
        for tool in ('create-order', 'auto-bind-coupons', 'draw-lottery', 'mall-create-order'):
            with self.assertRaises(ValueError):
                bridge.call(tool, {})

    def test_report_escapes_external_strings(self):
        result = demo(seed=24)
        result['meal']['store']['address'] = '<script>alert(1)</script>'
        html = render(result)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('离线模拟', html)

    def test_default_portion_and_unknown_classification(self):
        self.assertEqual(classify('麦当劳限定丝巾'), 'unknown')
        self.assertEqual(classify('北美招牌牧场酱'), 'unknown')
        self.assertEqual(classify('麦辣鸡腿汉堡'), 'main')
        self.assertEqual(classify('巨无霸'), 'main')
        nutrition = {'data': '[1]{productName,nutritionDescription,energyKj,energyKcal}:\n  麦乐鸡5块,null,890,213'}
        snapshot = prepare_snapshot({'datetime': 'now', 'data': {'meals': {'1': {'name': '麦乐鸡', 'currentPrice': '14'}}}},
                                    nutrition, {'storeCode': '1', 'storeName': '餐厅', 'address': '地址'},
                                    {'1': {'code': '1', 'name': '麦乐鸡5块', 'rounds': []}})
        self.assertEqual(snapshot['items'][0]['kcal'], 213)

    def test_same_physical_food_is_not_given_extra_random_weight(self):
        nutrition = {'data': '[1]{productName,nutritionDescription,energyKj,energyKcal}:\n  麦香鱼,null,1359,325'}
        menu = {'datetime': 'now', 'data': {'meals': {
            'a': {'name': '麦香鱼', 'currentPrice': '22'},
            'b': {'name': '麦香鱼单品精选', 'currentPrice': '20'}}}}
        details = {'a': {'code': 'a', 'name': '麦香鱼', 'rounds': []},
                   'b': {'code': 'b', 'name': '麦香鱼单品精选', 'rounds': [
                       {'id': 1, 'minQuantity': 1, 'choices': [{'code': 'a', 'name': '麦香鱼', 'quantity': 1, 'isDefault': 1}]}]}}
        snapshot = prepare_snapshot(menu, nutrition, {'storeCode': '1', 'storeName': '餐厅', 'address': '地址'}, details)
        self.assertEqual(len(snapshot['items']), 1)
        self.assertEqual(len(snapshot['items'][0]['alternates']), 1)

    def test_bundle_does_not_silently_change_portion(self):
        meal = {'items': [{'id': 'fries', 'components': [{'code': 'medium', 'name': '中薯条', 'quantity': 1}]}]}
        detail = {'code': 'bundle', 'name': '小薯条套餐', 'rounds': [{'id': 1, 'quantity': 1, 'minQuantity': 1, 'maxQuantity': 1,
                  'choices': [{'code': 'small', 'name': '小薯条'}]}]}
        self.assertEqual(bundle_offers(detail, meal), [])


if __name__ == '__main__':
    unittest.main()
