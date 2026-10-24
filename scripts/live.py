"""Adapter for the official MCP schema observed on 2026-10-24."""

import csv
import re
import math

from meal import amount_to_fen, draw, fingerprint
from mcp_readonly import ToolBusinessError, tool_data
from images import official_image
from request_binding import default_item
from pricing import bundle_offers, price_saved


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
    lines = text.splitlines()
    header = re.search(r'\{([^}]+)\}', lines[0] if lines else '')
    if not header:
        raise ValueError('官方营养字段缺失，无法确认每份 kcal')
    fields = next(csv.reader([header.group(1)], skipinitialspace=True))
    if 'productName' not in fields or 'energyKcal' not in fields:
        raise ValueError('官方营养字段已变更，不能用 kJ 或猜测值替代 kcal')
    name_index, energy_index = fields.index('productName'), fields.index('energyKcal')
    rows = csv.reader(lines[1:], skipinitialspace=True)
    result = {}
    for row in rows:
        if len(row) > max(name_index, energy_index):
            name = normalize_name(row[name_index])
            try:
                value = float(row[energy_index])
                if not math.isfinite(value) or value < 0:
                    value = None
            except ValueError:
                value = None
            if name in result and result[name] != value:
                result[name] = None
            else:
                result[name] = value
    return result
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
        if len(components) != 1 or components[0]['quantity'] != 1:
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
        image = official_image(entity.get('image'))
        if image:
            item.update(image_url=image, image_source='麦当劳官方菜单；仅为餐品示意，实际规格以文字为准')
        physical_key = fingerprint(sorted((c['code'], c['quantity']) for c in components))
        if physical_key in physical_items:
            physical_items[physical_key].setdefault('alternates', []).append(item)
        else:
            physical_items[physical_key] = item
            items.append(item)
    return {'mode': 'live', 'observed_at': menu['datetime'], 'source': '麦当劳官方 MCP',
            'store': {'id': store['storeCode'], 'name': store['storeName'], 'address': store['address']},
            'context': {'orderType': 1, 'beType': 1}, 'items': items, 'skipped': skipped}


def live_recommend(client, city, keyword, store_code=None, no_main=False, count=3):
    if type(count) is not int or not 1 <= count <= 6:
        raise ValueError('每次推荐 1 至 6 样，默认 3 样')
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
    details = {}
    detail_failures = []
    attempted = 0
    for code, entity in menu['data']['meals'].items():
        name = entity['name']
        if not entity.get('canWithOrder') and not re.search('套餐|件套|双人|分享餐|随心配|小食盘|开心乐园餐', name) and menu_kind(code, entity, menu) != 'unknown':
            if attempted >= 60:
                break
            attempted += 1
            try:
                details[code] = call('query-meal-detail', {**context, 'code': code})['data']
            except ToolBusinessError:
                detail_failures.append(name)
    snapshot = prepare_snapshot(menu, nutrition, store, details)
    meal = draw(snapshot, no_main=no_main, count=count)
    result = price_saved(client,meal,menu=menu,details=details,revalidate=False)
    result['verification'].update(eligible_items=len(snapshot['items']),detail_failures=detail_failures,
                                  excluded=snapshot['skipped'],store_selection='指定门店' if store_code else '接口返回的首家营业门店')
    return result
