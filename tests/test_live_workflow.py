"""Regression cases for the real adapter, CLI wiring and read-only recovery.

Responses in this file are synthetic fixtures, not additional live evidence.
"""
import copy
import io
import json
import itertools
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from images import official_image
from live import live_recommend, nutrition_map, prepare_snapshot
from main import demo, main
from meal import draw, single_person_sample
from mcp_readonly import MCP, ToolBusinessError
from report import render


class FixtureMCP:
    def __init__(self, reject_coupon=False, fail_coupon_query=False):
        self.calls = []
        self.reject_coupon = reject_coupon
        self.fail_coupon_query = fail_coupon_query

    def call(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == 'query-nearby-stores':
            data = [{'storeCode':'fixture','storeName':'测试餐厅','address':'模拟地址','businessStatus':True}]
        elif name == 'query-meals':
            data = {'meals':{str(i):{'name':('汉堡' if i < 4 else '鸡翅')+str(i),'currentPrice':'10','image':'https://menu-img.mcd.cn/test.png'} for i in range(10)}}
        elif name == 'query-meal-detail':
            data = {'code':arguments['code'],'name':('汉堡' if int(arguments['code']) < 4 else '鸡翅')+arguments['code'],'rounds':[]}
        elif name == 'list-nutrition-foods':
            data = '[0]{productName,nutritionDescription,energyKj,energyKcal}:\n'
        elif name == 'query-store-coupons':
            if self.fail_coupon_query:
                return {'structuredContent':{'success':False,'data':None}}
            data = [{'couponId':'fixture-once','couponCode':'fixture-code','products':[{'productCode':str(i)} for i in range(10)],'title':'模拟已有券'}]
        elif name == 'calculate-price':
            has_coupon = any('couponId' in i for i in arguments['items'])
            if has_coupon and self.reject_coupon:
                return {'structuredContent':{'success':False,'data':{'price':0}}}
            data = {'price':len(arguments['items'])*1000 - (100 if has_coupon else 0)}
        else:
            raise AssertionError(name)
        return {'structuredContent':{'success':True,'datetime':'2026-10-24 13:00:00（合成测试）','data':data}}


class LiveWorkflowTests(unittest.TestCase):
    def test_main_drink_and_dessert_caps_across_quantities_and_modes(self):
        fixture = json.loads((ROOT/'examples/demo.json').read_text(encoding='utf-8'))
        for quantity in range(1,7):
            for no_main in (False,True):
                for seed in range(100):
                    meal = draw(fixture,no_main,count=quantity,seed=seed)
                    kinds = Counter(i['kind'] for i in meal['items'])
                    self.assertEqual(kinds['main'],int(not no_main))
                    self.assertLessEqual(kinds['drink'],1)
                    self.assertLessEqual(kinds['dessert'],1)
                    self.assertEqual(len(meal['items']),quantity)
                    if quantity == 6:
                        self.assertGreaterEqual(kinds['main']+kinds['side'],4)

    def test_group_weights_match_every_eligible_combination(self):
        pool = [{'id':kind+str(i),'kind':kind} for kind in ('main','side','drink','dessert') for i in range(2)]
        expected = Counter()
        for basket in itertools.combinations(pool,3):
            kinds = Counter(i['kind'] for i in basket)
            if kinds['main'] == 1 and kinds['drink'] <= 1 and kinds['dessert'] <= 1:
                expected[tuple(kinds[k] for k in ('main','side','drink','dessert'))] += 1
        class TicketRNG:
            def __init__(self,ticket): self.ticket=ticket
            def randrange(self,total):
                self.asserted_total=total
                return self.ticket
            def sample(self,values,size): return values[:size]
            def shuffle(self,values): pass
        actual = Counter()
        for ticket in range(sum(expected.values())):
            rng = TicketRNG(ticket)
            basket = single_person_sample(pool,3,False,rng)
            self.assertEqual(rng.asserted_total,sum(expected.values()))
            kinds = Counter(i['kind'] for i in basket)
            actual[tuple(kinds[k] for k in ('main','side','drink','dessert'))] += 1
        self.assertEqual(actual,expected)

    def test_insufficient_savory_items_does_not_relax_caps(self):
        fixture = json.loads((ROOT/'examples/demo.json').read_text(encoding='utf-8'))
        fixture['items'] = [i for i in fixture['items'] if i['kind'] in ('drink','dessert') or i['id']=='burger']
        with self.assertRaisesRegex(ValueError,'单人餐规则'):
            draw(fixture,count=4)

    def test_extra_mains_cannot_replace_missing_sides(self):
        fixture = json.loads((ROOT/'examples/demo.json').read_text(encoding='utf-8'))
        fixture['items'] = [i for i in fixture['items'] if i['kind']=='main']
        with self.assertRaisesRegex(ValueError,'单人餐规则'):
            draw(fixture,count=2)

    def test_all_quantities_and_modes_keep_exact_baskets(self):
        for count in range(1,7):
            for no_main in (False,True):
                client = FixtureMCP()
                result = live_recommend(client,'模拟城市','模拟地标',no_main=no_main,count=count)
                items = result['meal']['items']
                self.assertEqual(len(items),count)
                self.assertEqual(len({i['id'] for i in items}),count)
                self.assertEqual(sum(i['kind']=='main' for i in items),int(not no_main))
                self.assertTrue(any(i['kind']!='drink' for i in items))
                for name, request in client.calls:
                    if name == 'calculate-price':
                        self.assertEqual({i['productCode'] for i in request['items']},{i['id'] for i in items})
                        self.assertEqual(sum(i['quantity'] for i in request['items']),count)
                self.assertIsNotNone(result['comparison']['best'])

    def test_invalid_quantity_fails_before_network(self):
        for count in (0,7,True,2.5,'3'):
            client = FixtureMCP()
            with self.assertRaises(ValueError):
                live_recommend(client,'城市','地标',count=count)
            self.assertEqual(client.calls,[])

    def test_demo_and_cli_forward_quantity(self):
        for count in range(1,7):
            self.assertEqual(len(demo(count=count)['meal']['items']),count)
        with tempfile.TemporaryDirectory() as directory:
            result = demo(count=6)
            argv = ['main.py','live','--city','模拟城市','--keyword','模拟地标','--count','6','--output',directory+'/result.json','--html',directory+'/result.html']
            with patch.object(sys,'argv',argv), patch('main.MCP'), patch('live.live_recommend',return_value=result) as run, patch('sys.stdout',new=io.StringIO()):
                main()
            self.assertEqual(run.call_args.args[-1],6)
            self.assertEqual(len(json.loads(Path(directory+'/result.json').read_text(encoding='utf-8'))['meal']['items']),6)

    def test_coupon_failure_retains_other_valid_quotes(self):
        result = live_recommend(FixtureMCP(reject_coupon=True),'城市','地标',count=3)
        self.assertTrue(result['comparison']['failed'])
        self.assertEqual(result['comparison']['best']['payable_fen'],3000)
        self.assertEqual(result['verification']['store_coupon_count'],1)

    def test_coupon_query_failure_is_not_reported_as_zero_coupons(self):
        result = live_recommend(FixtureMCP(fail_coupon_query=True),'城市','地标',count=2)
        self.assertIsNone(result['verification']['store_coupon_count'])
        self.assertIn('券未验证',result['comparison']['scope'])
        self.assertEqual(result['comparison']['best']['payable_fen'],2000)

    def test_protocol_failure_preserves_successful_quotes_and_marks_pending(self):
        client = FixtureMCP()
        original = client.call
        quote_count = 0
        def call(name, args):
            nonlocal quote_count
            if name == 'calculate-price':
                quote_count += 1
                if quote_count == 2:
                    return {'structuredContent':{'success':True,'datetime':'fixture','data':{}}}
            return original(name,args)
        client.call = call
        result = live_recommend(client,'城市','地标',count=3)
        self.assertEqual(quote_count,2)
        self.assertEqual(result['comparison']['best']['payable_fen'],3000)
        self.assertTrue(result['comparison']['failed'])
        self.assertTrue(result['comparison']['pending'])

    def test_hidden_bundle_is_excluded_from_draw_pool(self):
        menu = {'datetime':'fixture','data':{'meals':{'x':{'name':'汉堡超值精选','currentPrice':'20'}}}}
        details = {'x':{'code':'x','name':'汉堡超值精选','rounds':[{'id':1,'minQuantity':1,'choices':[{'code':'burger','name':'汉堡','isDefault':1,'quantity':2}]}]}}
        result = prepare_snapshot(menu,{'data':'[0]{productName,energyKcal}:\n'},{'storeCode':'s','storeName':'模拟门店','address':'模拟地址'},details)
        self.assertEqual(result['items'],[])
        self.assertEqual(result['skipped'],['汉堡超值精选'])

    def test_nutrition_uses_named_fields_and_preserves_unknown(self):
        values = nutrition_map('[3]{energyKcal,productName,energyKj}:\n  123,汉堡,999\n  null,鸡翅,999\n  NaN,牛奶,999')
        self.assertEqual(values,{'汉堡':123,'鸡翅':None,'牛奶':None})
        with self.assertRaises(ValueError):
            nutrition_map('[1]{productName,energyKj}:\n  汉堡,999')

    def test_official_images_are_optional_and_strictly_scoped(self):
        for value in ('javascript:alert(1)','http://menu-img.mcd.cn/a.png','https://menu-img.mcd.cn.evil.test/a','https://user@menu-img.mcd.cn/a','https://menu-img.mcd.cn/a?token=private',None):
            self.assertIsNone(official_image(value))
        self.assertEqual(official_image('https://menu-img.mcd.cn/a.png'),'https://menu-img.mcd.cn/a.png')
        result = demo(count=1)
        result['meal']['items'][0]['image_url'] = 'javascript:alert(1)'
        self.assertNotIn('javascript:',render(result))

    def test_transient_transport_retries_are_bounded(self):
        with patch.dict('os.environ',{'MCD_MCP_TOKEN':'fixture-not-a-real-credential'}):
            client = MCP()
        for failures in ([URLError('offline'),{'ok':True}], [HTTPError('https://mcp.mcd.cn',503,'unavailable',None,None),{'ok':True}]):
            with patch.object(client,'request',side_effect=failures) as request, patch('mcp_readonly.time.sleep'):
                self.assertEqual(client.rpc('tools/list',{}),{'ok':True})
                self.assertEqual(request.call_count,2)
        with patch.object(client,'request',side_effect=TimeoutError) as request, patch('mcp_readonly.time.sleep'):
            with self.assertRaisesRegex(ValueError,'有限重试'):
                client.rpc('tools/list',{})
            self.assertEqual(request.call_count,3)

    def test_auth_rate_limits_and_business_errors_are_not_retried(self):
        with patch.dict('os.environ',{'MCD_MCP_TOKEN':'fixture-not-a-real-credential'}):
            client = MCP()
        for code in (400,401,403,429):
            with patch.object(client,'request',side_effect=HTTPError('https://mcp.mcd.cn',code,'no',None,None)) as request:
                with self.assertRaisesRegex(ValueError,str(code)):
                    client.rpc('tools/list',{})
                self.assertEqual(request.call_count,1)
        with patch.object(client,'request',side_effect=ToolBusinessError('fixture')) as request:
            with self.assertRaises(ToolBusinessError):
                client.rpc('tools/list',{})
            self.assertEqual(request.call_count,1)
        with patch.object(client,'request') as request:
            with self.assertRaises(ValueError):
                client.rpc('tools/call',{'name':'create-order'})
            request.assert_not_called()

    def test_offline_doctor_does_not_connect_or_leak_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['main.py','doctor','--offline','--output',directory+'/doctor.json']
            with patch.object(sys,'argv',argv), patch.dict('os.environ',{'MCD_MCP_TOKEN':'fixture-private-value'}), patch('main.MCP') as client, patch('sys.stdout',new=io.StringIO()):
                main()
            text = Path(directory+'/doctor.json').read_text(encoding='utf-8')
            self.assertNotIn('fixture-private-value',text)
            self.assertTrue(json.loads(text)['token_configured'])
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
