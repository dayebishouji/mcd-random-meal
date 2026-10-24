"""Reprice a fixed basket using current official bundles, coupons and exact options."""
import itertools
import re
from collections import Counter

from external import compare_external, validate_external
from meal import amount_to_fen, fingerprint, optimize, select_best, validate_draw
from mcp_readonly import ToolBusinessError, tool_data
from request_binding import default_item, modification, same_contents


def bundle_offers(detail, meal, limits=None):
    target = Counter()
    for item in meal['items']:
        for component in item['components']:
            target[component['code']] += component['quantity']
    groups = detail.get('rounds', [])
    if not groups or any(type(g.get('quantity')) is not int or not 1 <= g['quantity'] <= len(meal['items']) or g.get('minQuantity') != g['quantity'] or g.get('maxQuantity') != g['quantity'] for g in groups):
        return []
    if sum(g['quantity'] for g in groups) > sum(target.values()):
        return []
    selections = []
    for group in groups:
        choices = list({c['code']:c for c in group.get('choices',[]) if c.get('code') in target}.values())
        selections.append(list(itertools.combinations(choices,group['quantity'])))
    if any(not choices for choices in selections):
        return []
    def variants(index, covered, picked):
        if index == len(selections):
            yield picked
            return
        for chosen in selections[index]:
            next_cover = covered + Counter(choice['code'] for choice in chosen)
            if next_cover <= target:
                yield from variants(index+1,next_cover,picked+[chosen])
    offers = []
    for index,picked in enumerate(itertools.islice(variants(0,Counter(),[]),129)):
        if index == 128:
            if limits is not None:
                limits['truncated'] = True
            break
        cover = Counter(choice['code'] for chosen in picked for choice in chosen)
        if not cover <= target:
            continue
        request = {'productCode':detail['code'],'quantity':1,**modification(detail),'roundList':[
            {'round':str(group['id']),'comboItemList':[{'code':choice['code'],'quantity':1,**modification(choice)} for choice in chosen]}
            for group,chosen in zip(groups,picked)]}
        match = None
        for size in range(1,len(meal['items'])+1):
            for subset in itertools.combinations(meal['items'],size):
                physical = Counter()
                for item in subset:
                    physical.update({c['code']:c['quantity'] for c in item['components']})
                if physical == cover and same_contents([request],[i['request_item'] for i in subset]):
                    match = {i['id']:1 for i in subset}
                    break
            if match:
                break
        if match:
            offers.append({'id':'bundle:'+detail['code']+':'+fingerprint(request)[:16], 'label':detail['name'],
                           'covers':match,'request_item':request,'conditions':'餐品、份数、规格及标准特调一致；官方整单核价确认',
                           'evidence':'当前 query-meal-detail 实际子项与请求选项逐项绑定'})
    return offers


def quote_offers(client, meal, offers, scope, max_plans=64, truncated=False):
    catalog = {'draw_id':meal['draw_id'],'mode':'live','store':meal['store'],'context':meal['context'],'offers':offers,'scope':scope}
    plans = optimize(meal,catalog,max_plans=max_plans)
    plans['truncated'] = plans['truncated'] or truncated
    quotes = []
    expected = [i['request_item'] for i in meal['items']]
    for plan in plans['plans']:
        items = [o['request_item'] for o in plan['offers']]
        if not same_contents(items,expected):
            raise ValueError('购买方案实际餐品、规格或份数与原餐单不一致，停止核价')
        try:
            payload = tool_data(client.call('calculate-price',{'storeCode':meal['store']['id'],**meal['context'],'items':items}))
            price = amount_to_fen(payload['data']['price'],'fen')
            quotes.append({'draw_id':meal['draw_id'],'mode':'live','plan_id':plan['id'],'status':'success',
                           'payable_fen':price,'quoted_at':payload['datetime'],'source':'麦当劳 MCP calculate-price 官方整单核价，单位分'})
        except ToolBusinessError as exc:
            quotes.append({'draw_id':meal['draw_id'],'mode':'live','plan_id':plan['id'],'status':'failed','reason':str(exc)})
        except (ValueError,KeyError,TypeError) as exc:
            quotes.append({'draw_id':meal['draw_id'],'mode':'live','plan_id':plan['id'],'status':'failed','reason':str(exc)})
            break
    return select_best(meal,plans,quotes)


def price_saved(client, meal, menu=None, details=None, revalidate=True, external=None):
    validate_draw(meal)
    if meal['mode'] != 'live' or meal['context'] != {'orderType':1,'beType':1}:
        raise ValueError('真实重新核价只支持已保存的到店取餐餐单')
    if external is not None:
        validate_external(meal,external)
    context = {'storeCode':meal['store']['id'],**meal['context']}
    def call(name,args):
        return tool_data(client.call(name,args))
    menu = menu if menu is not None else call('query-meals',context)
    details = dict(details or {})
    warnings = []
    if revalidate:
        for item in meal['items']:
            entity = menu['data']['meals'].get(item['id'])
            if not entity or entity.get('canWithOrder'):
                raise ValueError('原餐品已不在当前可用菜单，保留餐单并停止，不自动换餐')
            current = call('query-meal-detail',{**context,'code':item['id']})['data']
            details[item['id']] = current
            request,_ = default_item(current)
            if not same_contents([request],[item['request_item']]):
                raise ValueError('原餐品默认规格或特调已改变，不能把新规格当同一餐单核价')
    try:
        coupons = call('query-store-coupons',context)['data']
        coupon_count = len(coupons)
    except ToolBusinessError:
        coupons,coupon_count = [],None
        warnings.append('券未验证：门店券查询失败，不代表账号无券')
    singles = [{'id':'single:'+i['id'],'label':i['name']+'单点','covers':{i['id']:1},
                'request_item':i['request_item'],'evidence':i['evidence']} for i in meal['items']]
    offers = list(singles)
    for item in meal['items']:
        for alternate in item.get('alternates',[]):
            entity = menu['data']['meals'].get(alternate['id'])
            if not entity or entity.get('canWithOrder'):
                continue
            if revalidate:
                current = call('query-meal-detail',{**context,'code':alternate['id']})['data']
                request,_ = default_item(current)
            else:
                request = alternate['request_item']
            if same_contents([request],[item['request_item']]):
                offers.append({'id':'alternate:'+alternate['id'],'label':alternate['name']+'等价入口','covers':{item['id']:1},
                               'request_item':request,'evidence':'当前默认组成、数量与特调一致'})
    candidates = [(code,entity) for code,entity in menu['data']['meals'].items()
                  if not entity.get('canWithOrder') and re.search('套餐|件套|随心配|单人餐|双人|分享|小食盘|开心乐园餐|精选',entity['name'])]
    candidates.sort(key=lambda pair:('随心配' not in pair[1]['name'],pair[0]))
    checked = 0
    variant_limits = {'truncated':False}
    for code,entity in candidates[:60]:
        checked += 1
        try:
            if code not in details:
                details[code] = call('query-meal-detail',{**context,'code':code})['data']
            offers.extend(bundle_offers(details[code],meal,variant_limits))
        except ToolBusinessError:
            warnings.append('部分套餐详情查询失败，未比较该入口')
    for coupon in coupons:
        if not coupon.get('couponId') or not coupon.get('couponCode'):
            continue
        codes = {p['productCode'] for p in coupon.get('products',[])}
        for offer in list(offers):
            if offer['id'].startswith('coupon:') or offer['request_item']['productCode'] not in codes:
                continue
            offers.append({**offer,'id':'coupon:'+coupon['couponId']+':'+offer['id'],
                           'label':coupon.get('title','门店可用券')+' / '+offer['label'],
                           'request_item':{**offer['request_item'],'couponId':coupon['couponId'],'couponCode':coupon['couponCode']},
                           'exclusive_groups':['coupon:'+coupon['couponId']],
                           'conditions':coupon.get('tradeDateTime','本店当前可用，官方整单核价确认')})
    seen,unique = set(),[]
    for offer in offers:
        key = fingerprint(offer['request_item'])
        if key not in seen:
            seen.add(key); unique.append(offer)
    baseline = [o for o in unique if o['id'].startswith('single:')]
    alternatives = sorted((o for o in unique if not o['id'].startswith('single:')),key=lambda o:(-sum(o['covers'].values()),o['id']))
    all_count = len(unique)
    offers = baseline+alternatives[:120-len(baseline)]
    truncated = checked < len(candidates) or all_count > 120 or variant_limits['truncated']
    scope = f'固定餐单；检查 {checked}/{len(candidates)} 个套餐/随心配入口、单点及'+('当前门店已有券' if coupon_count is not None else '券未验证')+'；不含主动领券或开卡'
    if warnings:
        scope += '；'+'；'.join(dict.fromkeys(warnings))
    comparison = quote_offers(client,meal,offers,scope,truncated=truncated)
    result = {'meal':meal,'comparison':comparison,'verification':{
        'store_coupon_count':coupon_count,'menu_items':len(menu['data']['meals']),'bundle_entries_checked':checked,
        'bundle_entries_total':len(candidates),'offers_before_limit':all_count,'successful_quotes':len(comparison['quotes']),
        'network_retries':getattr(client,'retry_count',0),'warnings':warnings,'reprice_only':revalidate}}
    if external is not None:
        result['external_comparison'] = compare_external(meal,external,lambda remaining:quote_offers(client,remaining,offers,scope,max_plans=24,truncated=truncated))
    return result
