"""Catalog provenance, exact bundle matching and explicit bundle-mode regressions."""
import copy,json,sys,unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from bundle_recommend import bundle_meal
from images import official_image
from live import live_recommend
from main import demo
from pricing import bundle_offers
from test_live_workflow import FixtureMCP


class BundleMCP(FixtureMCP):
    def call(self,name,args):
        if name=='query-meal-detail' and args['code']=='BUNDLE':
            self.calls.append((name,copy.deepcopy(args)))
            detail={'code':'BUNDLE','name':'合成测试套餐','rounds':[{'id':n,'quantity':1,'minQuantity':1,'maxQuantity':1,'choices':[{'code':code,'name':code,'quantity':1,'isDefault':1}]} for n,code in enumerate(('0','4','5'),1)]}
            return {'structuredContent':{'success':True,'datetime':'fixture','data':detail}}
        result=super().call(name,args)
        if name=='query-meals':result['structuredContent']['data']['meals']['BUNDLE']={'name':'合成测试套餐','currentPrice':'20'}
        return result


class CatalogTests(unittest.TestCase):
    def test_reference_does_not_claim_permanent_availability(self):
        data=json.loads((ROOT/'references/menu-catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(data['mode'],'reference');self.assertIn('无永久/常驻标记',data['availability_notice'])
        self.assertEqual(len(data['checked_stores']),3)
        self.assertEqual(len({i['id'] for i in data['items']}),len(data['items']))
        self.assertTrue(any(i['kcal'] is None for i in data['items']))
        self.assertTrue(any(not i['common_reference'] for i in data['items']))
        for item in data['items']:
            self.assertEqual(len(item['components']),1);self.assertEqual(item['components'][0]['quantity'],1)
            self.assertIn(item['detail_verified_store_id'],item['seen_menu_store_ids'])
            if item.get('image_url'):self.assertEqual(official_image(item['image_url']),item['image_url'])

    def test_each_official_quote_still_matches_saved_bundle_options(self):
        data=json.loads((ROOT/'references/bundle-catalog.json').read_text(encoding='utf-8'))
        catalog=json.loads((ROOT/'references/menu-catalog.json').read_text(encoding='utf-8'))
        items={i['id']:i for i in catalog['items']};bundles={b['id']:b for b in data['bundles']}
        for quote in data['verified_quotes']:
            entry=bundles[quote['bundle_code']]
            detail={**entry,'code':entry['id']}
            meal={'items':[items[i] for i in quote['item_ids']]}
            offers=bundle_offers(detail,meal)
            self.assertTrue(any(o['covers']==dict.fromkeys(quote['item_ids'],1) for o in offers),quote['name'])
            kinds=Counter(i['kind'] for i in meal['items'])
            self.assertLessEqual(kinds['main'],1);self.assertLessEqual(kinds['drink'],1);self.assertLessEqual(kinds['dessert'],1)
            self.assertIs(type(quote['bundle_price_fen']),int);self.assertGreaterEqual(quote['baseline_price_fen'],quote['bundle_price_fen'])

    def test_expanded_demo_has_no_unobserved_added_foods(self):
        fixture=json.loads((ROOT/'examples/demo.json').read_text(encoding='utf-8'))
        catalog=json.loads((ROOT/'references/menu-catalog.json').read_text(encoding='utf-8'))
        items={i['id']:i for i in catalog['items']}
        added=[i for i in fixture['items'] if i.get('catalog_id')]
        self.assertGreater(len(added),20)
        for item in added:
            source=items[item['catalog_id']]
            self.assertTrue(source['common_reference']);self.assertEqual(item['name'],'演示'+source['name']);self.assertEqual(item['kcal'],source['kcal'])
        self.assertLessEqual(len(fixture['offers']),120)

    def test_live_bundle_mode_revalidates_and_keeps_single_person_rules(self):
        template={'bundle_code':'BUNDLE','item_ids':['0','4','5']}
        client=BundleMCP()
        with patch('bundle_recommend.load_templates',return_value=[template,template]):
            result=live_recommend(client,'城市','地标',count=3,bundle_mode=True)
        self.assertEqual(set(result['meal']['basket']),{'0','4','5'})
        self.assertEqual(result['verification']['eligible_bundle_recipes'],1)
        self.assertEqual(result['verification']['recommendation_mode'],'bundle')
        self.assertEqual(result['comparison']['best']['payable_fen'],1000)
        self.assertEqual(sum(i['kind']=='main' for i in result['meal']['items']),1)

    def test_bundle_mode_does_not_relax_quantity_or_main_preferences(self):
        template={'bundle_code':'BUNDLE','item_ids':['0','4','5']}
        for quantity,no_main in ((6,False),(3,True)):
            client=BundleMCP()
            with patch('bundle_recommend.load_templates',return_value=[template]),self.assertRaisesRegex(ValueError,'没有符合'):
                live_recommend(client,'城市','地标',count=quantity,no_main=no_main,bundle_mode=True)
            self.assertNotIn('calculate-price',[name for name,_ in client.calls])


if __name__=='__main__':unittest.main()
