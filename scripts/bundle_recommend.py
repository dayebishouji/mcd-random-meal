"""Choose a known single-person bundle recipe, revalidated against the live menu."""
import json
import random
from collections import Counter
from pathlib import Path

from meal import draw,fingerprint
from mcp_readonly import ToolBusinessError,tool_data
from pricing import bundle_offers


def load_templates():
    path=Path(__file__).resolve().parents[1]/'references/bundle-catalog.json'
    return json.loads(path.read_text(encoding='utf-8'))['verified_quotes']


def bundle_meal(client,snapshot,menu,details,count,no_main):
    items_by_id={i['id']:i for i in snapshot['items']}
    candidates={};checked=0
    context={'storeCode':snapshot['store']['id'],**snapshot['context']}
    for template in load_templates():
        ids=template['item_ids'];code=template['bundle_code']
        if len(ids)!=count or code not in menu['data']['meals'] or menu['data']['meals'][code].get('canWithOrder') or not all(i in items_by_id for i in ids):continue
        items=[items_by_id[i] for i in ids];kinds=Counter(i['kind'] for i in items)
        if len(set(ids))!=len(ids) or kinds['main']!=int(not no_main) or kinds['drink']>1 or kinds['dessert']>1 or all(i['kind']=='drink' for i in items):continue
        checked+=1
        try:
            if code not in details:
                details[code]=tool_data(client.call('query-meal-detail',{**context,'code':code}))['data']
            offers=bundle_offers(details[code],{'items':items})
        except ToolBusinessError:continue
        if any(len(o['covers'])==count for o in offers):
            candidates[tuple(sorted(ids))]=items
    if not candidates:
        raise ValueError('当前已核实套餐模板中，没有符合数量和主食偏好的可售搭配；可选2–3样重试，或使用普通随机，不会自动加餐或放宽限制')
    selected=random.SystemRandom().choice(list(candidates.values()))
    meal=draw({**snapshot,'items':selected},no_main=no_main,count=count)
    meal['random_policy']='用户显式套餐模式：在当前菜单与规格核验通过的本地套餐模板所覆盖的不同餐单中等概率抽取，再比较同餐单买法；不按价格加权'
    meal['draw_id']=fingerprint({k:v for k,v in meal.items() if k!='draw_id'})
    return meal,{'bundle_templates_checked':checked,'eligible_bundle_recipes':len(candidates),
                 'recommendation_mode':'bundle','bundle_template_scope':'随Skill附带的已核价参考搭配，非所有套餐变体；价格仍以本轮官方整单核价为准'}
