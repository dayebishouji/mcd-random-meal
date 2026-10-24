"""Fixed-basket repricing and user-reference voucher regression fixtures."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from external import compare_external
from live import live_recommend
from main import demo, main, price_demo
from meal import draw, fingerprint, optimize
from pricing import bundle_offers, price_saved
from report import render
from request_binding import request_contents, same_contents
from test_live_workflow import FixtureMCP


def voucher(meal, covers=None):
    return {'draw_id':meal['draw_id'],'store_id':meal['store']['id'],'context':meal['context'],
            'offers':[{'id':'user-1','platform':'美团','label':'用户提供的随心配参考',
                       'purchase_fen':1300,'extra_fen':200,'covers':covers or {meal['items'][0]['id']:1},
                       'conditions':'仅为测试，门店/日期/规格/费用待核对','confirmed':False}]}


def fixed_live():
    return live_recommend(FixtureMCP(),'城市','地标',count=3)['meal']


class RepricingTests(unittest.TestCase):
    def test_binding_compares_children_quantities_and_modifications(self):
        singles = [{'productCode':'burger','quantity':1},{'productCode':'fries','quantity':1}]
        bundle = [{'productCode':'combo','quantity':1,'roundList':[{'round':'1','comboItemList':[{'code':'burger','quantity':1},{'code':'fries','quantity':1}]}]}]
        self.assertTrue(same_contents(singles,bundle))
        for changed in ('quantity','code','modification'):
            wrong = copy.deepcopy(bundle)
            wrong[0]['roundList'][0]['comboItemList'][0][changed] = {'quantity':2,'code':'other','modification':{'values':[{'code':'ice','key':'no','quantity':0}]}}[changed]
            self.assertFalse(same_contents(singles,wrong))

    def test_binding_rejects_ambiguous_parent_and_duplicate_rounds(self):
        for product in ({'productCode':'c','quantity':2,'roundList':[{'round':'1','comboItemList':[{'code':'a','quantity':1}]}]},
                        {'productCode':'c','quantity':1,'roundList':[{'round':'1','comboItemList':[{'code':'a','quantity':1}]}]*2}):
            with self.assertRaises(ValueError): request_contents({'items':[product]})

    def test_reprice_preserves_every_item_and_never_draws(self):
        meal = fixed_live(); original = copy.deepcopy(meal); client = FixtureMCP()
        with patch('meal.draw',side_effect=AssertionError('must not draw')):
            result = price_saved(client,meal)
        self.assertEqual(result['meal'],original)
        self.assertTrue(result['verification']['reprice_only'])
        self.assertNotIn('query-nearby-stores',[name for name,_ in client.calls])

    def test_changed_default_spec_stops_before_any_quote(self):
        meal = fixed_live(); client = FixtureMCP(); original = client.call
        def call(name,args):
            value = original(name,args)
            if name == 'query-meal-detail': value['structuredContent']['data']['code'] = 'different'
            return value
        client.call = call
        with self.assertRaisesRegex(ValueError,'规格'): price_saved(client,meal)
        self.assertNotIn('calculate-price',[name for name,_ in client.calls])

    def test_late_bundle_beyond_old_twelve_entry_limit_is_quoted(self):
        meal = fixed_live(); client = FixtureMCP(); original = client.call
        def call(name,args):
            if name == 'query-meal-detail' and args['code'].startswith('bundle'):
                ids = [i['id'] for i in meal['items']] if args['code']=='bundle19' else ['missing']
                detail = {'code':args['code'],'name':'随心配测试','rounds':[{'id':1,'quantity':len(ids),'minQuantity':len(ids),'maxQuantity':len(ids),'choices':[{'code':i,'name':i} for i in ids]}]}
                return {'structuredContent':{'success':True,'datetime':'fixture','data':detail}}
            value = original(name,args)
            if name == 'query-meals':
                value['structuredContent']['data']['meals'].update({f'bundle{i:02d}':{'name':'随心配测试','currentPrice':'30'} for i in range(20)})
            if name == 'calculate-price' and any(i['productCode']=='bundle19' for i in args['items']):
                value['structuredContent']['data']['price'] = 1300
            return value
        client.call = call
        result = price_saved(client,meal)
        self.assertEqual(result['comparison']['best']['payable_fen'],1300)
        self.assertEqual(result['verification']['bundle_entries_checked'],20)
        self.assertEqual(result['meal'],meal)

    def test_round_requiring_two_distinct_items_and_exact_options(self):
        meal = fixed_live(); ids = [i['id'] for i in meal['items'][:2]]
        detail = {'code':'bundle','name':'两件测试','rounds':[{'id':1,'quantity':2,'minQuantity':2,'maxQuantity':2,'choices':[{'code':i,'name':i} for i in ids]}]}
        offers = bundle_offers(detail,meal)
        self.assertEqual(len(offers),1)
        self.assertEqual(offers[0]['covers'],dict.fromkeys(ids,1))
        self.assertTrue(same_contents([offers[0]['request_item']],[i['request_item'] for i in meal['items'][:2]]))

    def test_plan_limit_keeps_baseline_and_marks_truncation(self):
        meal = demo(count=1)['meal']; code = meal['items'][0]['id']
        offers = [{'id':('single:' if n==0 else 'deal:')+str(n),'label':'fixture','covers':{code:1},'evidence':'fixture'} for n in range(80)]
        result = optimize(meal,{**meal,'offers':offers},max_plans=4)
        self.assertTrue(result['truncated']); self.assertEqual(len(result['plans']),4)
        self.assertTrue(result['plans'][0]['offer_ids'][0].startswith('single:'))

    def test_bundle_variant_limit_reports_unexamined_permutations(self):
        meal = live_recommend(FixtureMCP(),'城市','地标',count=6)['meal']
        choices = [{'code':i['id'],'name':i['name']} for i in meal['items']]
        detail = {'code':'bundle','name':'六轮测试','rounds':[{'id':n,'quantity':1,'minQuantity':1,'maxQuantity':1,'choices':choices} for n in range(6)]}
        limits = {'truncated':False}
        offers = bundle_offers(detail,meal,limits)
        self.assertEqual(len(offers),128); self.assertTrue(limits['truncated'])
        self.assertTrue(all(offer['covers']==meal['basket'] for offer in offers))

    def test_external_partial_quotes_whole_remainder_not_menu_subtraction(self):
        meal = demo(seed=1)['meal']; document = voucher(meal); seen = []
        def quote(remaining):
            seen.append(remaining)
            return {'best':{'payable_fen':789,'labels':['余餐整单测试']},'failed':[],'pending':[]}
        result = compare_external(meal,document,quote)
        self.assertEqual(result['best']['reference_total_fen'],1300+200+789)
        self.assertEqual(len(seen[0]['items']),2)
        self.assertEqual(result['status'],'user_reference_only')
        self.assertFalse(result['best']['confirmed'])

    def test_external_full_coverage_zero_remainder_never_calls_official(self):
        meal = demo()['meal']; quote = unittest.mock.Mock(side_effect=AssertionError('unneeded'))
        result = compare_external(meal,voucher(meal,meal['basket']),quote)
        self.assertEqual(result['best']['reference_total_fen'],1500)
        self.assertEqual(result['best']['remaining_fen'],0); quote.assert_not_called()

    def test_external_invalid_documents_stop_before_network(self):
        meal = fixed_live(); original = voucher(meal)
        bad = [[],{}, {**original,'draw_id':'other'}, {**original,'store_id':'other'}, {**original,'context':{'orderType':2}}]
        for key,value in [('covers',{'missing':1}),('covers',{meal['items'][0]['id']:2}),('purchase_fen',13.5),('extra_fen',True),('confirmed','yes'),('conditions','')]:
            document = copy.deepcopy(original); document['offers'][0][key]=value; bad.append(document)
        duplicated = copy.deepcopy(original); duplicated['offers']*=2; bad.append(duplicated)
        for document in bad:
            client = FixtureMCP()
            with self.subTest(document=document), self.assertRaises(ValueError): price_saved(client,meal,external=document)
            self.assertEqual(client.calls,[])

    def test_external_unquoted_remainder_has_no_reference_total(self):
        meal = demo()['meal']
        result = compare_external(meal,voucher(meal),lambda _: {'best':None,'failed':[{}],'pending':[]})
        self.assertIsNone(result['best']); self.assertIsNone(result['offers'][0]['reference_total_fen'])

    def test_external_is_independent_and_html_escaped(self):
        meal = demo(seed=3)['meal']; original = price_demo(meal)
        document = voucher(meal); document['offers'][0]['conditions']='<script>alert(1)</script>'
        result = price_demo(meal,document)
        self.assertEqual(result['comparison'],original['comparison']); self.assertEqual(result['meal'],meal)
        html = render(result)
        self.assertNotIn('<script>',html); self.assertIn('&lt;script&gt;',html); self.assertIn('外部平台券',html)

    def test_cli_reprice_demo_does_not_draw_or_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            result = demo(seed=5,count=6); source=Path(folder)/'input.json'; target=Path(folder)/'result.json'
            source.write_text(json.dumps(result),encoding='utf-8')
            argv=['main.py','reprice','--input',str(source),'--output',str(target),'--html',folder+'/result.html']
            with patch.object(sys,'argv',argv), patch('main.draw',side_effect=AssertionError('redraw')), patch('main.MCP') as client, patch('sys.stdout',new=io.StringIO()): main()
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['meal'],result['meal']); client.assert_not_called()


if __name__ == '__main__': unittest.main()
