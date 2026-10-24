"""Adapter for the official MCP schema observed on 2026-10-24."""

import csv
import itertools
import re
from collections import Counter

from meal import amount_to_fen, draw, fingerprint, optimize, select_best
from mcp_readonly import tool_data


def classify(name):
    if re.search('周边|丝巾|玩具|酱$|餐具|会员|金卡', name):
        return 'unknown'
    if re.search('巨无霸|堡|麦香鱼|麦香鸡|麦满分|三明治|卷|粥|米饭|面条', name):
        return 'main'
    if re.search('冰淇淋|麦旋风|新地|派$|蛋糕|拉明顿|圆筒', name):
        return 'dessert'
    if re.search('鸡翅|鸡排|麦乐鸡|脆汁鸡|鸡球|薯条|扭扭薯|玉米|薯饼|油条|炸鸡', name):
        return 'side'
    if re.search('可乐|雪碧|茶|咖啡|美式|奶铁|牛奶|豆浆|奶|果汁|苹果汁|橙|怡泉|麦炫酷|雪冰|纯悦|卡布奇诺', name):
        return 'drink'
    return 'unknown'


def normalize_name(name):
    name = re.sub(r'^麦咖啡[™®]?', '', name)
    return re.sub(r'\s+', '', name).replace('(', '（').replace(')', '）')


def menu_kind(code, entity, menu):
    kind = classify(entity['name'])
    if kind != 'unknown' or re.search('周边|丝巾|玩具|酱$|餐具|会员|金卡', entity['name']):
        return kind
    for category in menu['data'].get('categories', []):
        if category['name'] in ('饮品', '麦咖啡™') and any(m['code'] == code for m in category.get('meals', [])):
            return 'drink'
    return 'unknown'


def nutrition_map(text):
    rows = list(csv.reader(text.splitlines()[1:], skipinitialspace=True))
    result = {}
    for row in rows:
        if len(row) >= 4:
            name = normalize_name(row[0])
            value = float(row[3])
            if name in result and result[name] != value:
                result[name] = None
            else:
                result[name] = value
    return result


def modification(entity):
    values = []
    for group in entity.get('modification', {}).get('items', []):
        for option in group.get('values', []):
            quantity = option.get('selectedQuantity', 0)
            key = option.get('selectedKey') if quantity else option.get('unselectedKey')
            if key is not None:
                values.append({'code': option['code'], 'key': key, 'quantity': quantity})
    return {'modification': {'values': values}} if values else {}


def default_item(detail):
    request = {'productCode': detail['code'], 'quantity': 1, **modification(detail)}
    components = []
    rounds = []
    for group in detail.get('rounds', []):
        selected = [c for c in group.get('choices', []) if c.get('isDefault') == 1 and c.get('quantity', 0) > 0]
        total = sum(c['quantity'] for c in selected)
        if not selected or total < group.get('minQuantity', 0):
            raise ValueError('餐品缺少完整默认规格')
        rounds.append({'round': str(group['id']), 'comboItemList': [
            {'code': c['code'], 'quantity': c['quantity'], **modification(c)} for c in selected]})
        components.extend({'code': c['code'], 'name': c['name'], 'quantity': c['quantity']} for c in selected)
    if rounds:
        request['roundList'] = rounds
    else:
        components = [{'code': detail['code'], 'name': detail['name'], 'quantity': 1}]
    return request, components


def prepare_snapshot(menu, nutrition, store, details):
    calories = nutrition_map(nutrition['data'])
    items = []
    skipped = []
    physical_items = {}
    for code, entity in menu['data']['meals'].items():
        name = entity['name']
        if entity.get('canWithOrder') or re.search('套餐|件套|双人|分享餐|随心配|小食盘|开心乐园餐', name):
            continue
        kind = menu_kind(code, entity, menu)
        if kind == 'unknown' or code not in details:
            skipped.append(name)
            continue
        detail = details[code]
        try:
            request, components = default_item(detail)
        except ValueError:
            skipped.append(name)
            continue
        component_calories = [calories.get(normalize_name(c['name'])) for c in components]
        kcal = None if any(v is None for v in component_calories) else sum(v*c['quantity'] for v, c in zip(component_calories, components))
        display_name = ' + '.join(c['name'] + (f"×{c['quantity']}" if c['quantity'] != 1 else '') for c in components)
        if any(classify(c['name']) == 'main' for c in components):
            kind = 'main'
        item = {'id': code, 'name': display_name, 'kind': kind, 'selectable': True,
                      'menu_fen': amount_to_fen(entity['currentPrice'], 'yuan'), 'kcal': kcal,
                      'components': components, 'request_item': request,
                      'evidence': '当前门店 query-meals + query-meal-detail 默认规格；热量按官方精确名称匹配'}
        physical_key = fingerprint(sorted((c['code'], c['quantity']) for c in components))
        if physical_key in physical_items:
            physical_items[physical_key].setdefault('alternates', []).append(item)
        else:
            physical_items[physical_key] = item
            items.append(item)
    return {'mode': 'live', 'observed_at': menu['datetime'], 'source': '麦当劳官方 MCP',
            'store': {'id': store['storeCode'], 'name': store['storeName'], 'address': store['address']},
            'context': {'orderType': 1, 'beType': 1}, 'items': items, 'skipped': skipped}


def bundle_offers(detail, meal):
    """Only construct bundles with identical physical product codes and quantities."""
    target = Counter()
    for item in meal['items']:
        for component in item['components']:
            target[component['code']] += component['quantity']
    groups = detail.get('rounds', [])
    if not groups or any(g.get('quantity') != 1 or g.get('minQuantity') != 1 or g.get('maxQuantity') != 1 for g in groups):
        return []
    choices = [[c for c in g.get('choices', []) if c['code'] in target] for g in groups]
    if any(not group for group in choices):
        return []
    offers = []
    for picked in itertools.islice(itertools.product(*choices), 64):
        cover = Counter(c['code'] for c in picked)
        if not cover <= target:
            continue
        match = None
        for count in range(1, len(meal['items']) + 1):
            for subset in itertools.combinations(meal['items'], count):
                physical = Counter()
                for item in subset:
                    physical.update({c['code']: c['quantity'] for c in item['components']})
                if physical == cover:
                    match = {item['id']: 1 for item in subset}
                    break
            if match:
                break
        if not match:
            continue
        request = {'productCode': detail['code'], 'quantity': 1, 'roundList': [
            {'round': str(group['id']), 'comboItemList': [{'code': choice['code'], 'quantity': 1, **modification(choice)}]}
            for group, choice in zip(groups, picked)]}
        offers.append({'id': detail['code'] + ':' + ':'.join(c['code'] for c in picked),
                       'label': detail['name'], 'covers': match, 'request_item': request,
                       'conditions': '相同餐品与份数，标准特调；官方整单核价确认',
                       'evidence': 'query-meal-detail 返回的实际可选组成，商品编码逐项相等'})
    return offers


def live_recommend(client, city, keyword, store_code=None, no_main=False):
    def call(name, arguments):
        return tool_data(client.call(name, arguments))
    stores = call('query-nearby-stores', {'city': city, 'keyword': keyword, 'beType': 1, 'searchType': 2})['data']
    candidates = [s for s in stores if s.get('businessStatus') is True and s.get('address')]
    store = next((s for s in candidates if s['storeCode'] == store_code), None) if store_code else next(iter(candidates), None)
    if not store:
        raise ValueError('未返回符合条件的营业门店，请换地标或门店编码')
    context = {'storeCode': store['storeCode'], 'orderType': 1, 'beType': 1}
    menu = call('query-meals', context)
    nutrition = call('list-nutrition-foods', {})
    coupons = call('query-store-coupons', context)
    details = {}
    for code, entity in menu['data']['meals'].items():
        name = entity['name']
        if not entity.get('canWithOrder') and not re.search('套餐|件套|双人|分享餐|随心配|小食盘|开心乐园餐', name) and menu_kind(code, entity, menu) != 'unknown':
            if len(details) >= 60:
                break
            details[code] = call('query-meal-detail', {**context, 'code': code})['data']
    snapshot = prepare_snapshot(menu, nutrition, store, details)
    meal = draw(snapshot, no_main=no_main)
    offers = [{'id': 'single:' + item['id'], 'label': item['name'] + '单点', 'covers': {item['id']: 1},
               'request_item': item['request_item'], 'evidence': item['evidence']} for item in meal['items']]
    for item in meal['items']:
        for alternate in item.get('alternates', []):
            offers.append({'id': 'alternate:' + alternate['id'], 'label': alternate['name'] + '等价菜单入口',
                           'covers': {item['id']: 1}, 'request_item': alternate['request_item'],
                           'evidence': '默认餐品组成编码与数量完全一致的另一菜单入口'})
    for coupon in coupons['data']:
        if not coupon.get('couponId') or not coupon.get('couponCode'):
            continue
        codes = {p['productCode'] for p in coupon.get('products', [])}
        for item in meal['items']:
            if item['id'] in codes:
                offers.append({'id': 'coupon:' + coupon['couponId'] + ':' + item['id'],
                               'label': coupon.get('title', '门店可用券'), 'covers': {item['id']: 1},
                               'request_item': {**item['request_item'], 'couponId': coupon['couponId'], 'couponCode': coupon['couponCode']},
                               'exclusive_groups': ['coupon:' + coupon['couponId']],
                               'conditions': coupon.get('tradeDateTime', '本店当前可用，核价确认'),
                               'evidence': 'query-store-coupons 的当前门店适用商品编码'})
    chosen_names = [c['name'] for i in meal['items'] for c in i['components']]
    bundles = [(code, e) for code, e in menu['data']['meals'].items()
               if not e.get('canWithOrder') and re.search('套餐|件套|随心配|单人餐', e['name'])]
    bundles.sort(key=lambda pair: (not any(n in pair[1]['name'] for n in chosen_names), '随心配' not in pair[1]['name'], pair[0]))
    checked = 0
    for code, entity in bundles[:12]:
        detail = call('query-meal-detail', {**context, 'code': code})['data']
        checked += 1
        offers.extend(bundle_offers(detail, meal))
    offers_trimmed = len(offers) > 40
    if offers_trimmed:
        offers = offers[:40]
    catalog = {'draw_id': meal['draw_id'], 'mode': 'live', 'store': meal['store'], 'context': meal['context'],
               'offers': offers, 'scope': f'单点、当前门店已有券与 {checked} 个套餐入口；不含付费开卡或新增领券'}
    plans = optimize(meal, catalog)
    plans['truncated'] = plans['truncated'] or offers_trimmed
    quotes = []
    for plan in plans['plans']:
        request = {**context, 'items': [o['request_item'] for o in plan['offers']]}
        try:
            response = call('calculate-price', request)
            price = amount_to_fen(response['data']['price'], 'fen')
            quotes.append({'draw_id': meal['draw_id'], 'mode': 'live', 'plan_id': plan['id'],
                           'status': 'success', 'payable_fen': price, 'quoted_at': response['datetime'],
                           'source': '麦当劳 MCP calculate-price /data/price，单位分'})
        except ValueError as exc:
            quotes.append({'draw_id': meal['draw_id'], 'mode': 'live', 'plan_id': plan['id'],
                           'status': 'failed', 'reason': str(exc)})
            break
    return {'meal': meal, 'comparison': select_best(meal, plans, quotes),
            'verification': {'store_coupon_count': len(coupons['data']), 'menu_items': len(menu['data']['meals']),
                             'eligible_items': len(snapshot['items']), 'bundle_entries_checked': checked,
                             'successful_quotes': sum(q['status'] == 'success' for q in quotes),
                             'store_selection': '指定门店' if store_code else '接口返回的首家营业门店',
                             'excluded': snapshot['skipped']}}
