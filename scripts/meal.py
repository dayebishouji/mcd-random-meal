"""Random meal selection and exact-basket purchase comparison (standard library)."""

import hashlib
import json
import math
import random
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cents(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('金额必须为非负整数分')
    return value


def validate_draw(meal):
    if fingerprint({key: value for key, value in meal.items() if key != 'draw_id'}) != meal.get('draw_id'):
        raise ValueError('餐单内容已改变，本次报价失效；请重新抽取并核价')


def validate_snapshot(snapshot):
    if snapshot.get('mode') not in ('demo', 'live'):
        raise ValueError('数据模式必须明确为 demo 或 live')
    if not snapshot.get('observed_at') or not snapshot.get('source'):
        raise ValueError('缺少数据来源或时间')
    store = snapshot.get('store', {})
    if not all(store.get(key) for key in ('id', 'name', 'address')):
        raise ValueError('门店必须包含编码、名称和完整地址')
    if not snapshot.get('context'):
        raise ValueError('缺少取餐方式等本次场景')
    items = snapshot.get('items', [])
    if not items or len(items) > 500:
        raise ValueError('餐品数量应为 1 至 500')
    seen = set()
    for item in items:
        if not item.get('id') or item['id'] in seen or not item.get('name'):
            raise ValueError('餐品必须有唯一编码及名称')
        seen.add(item['id'])
        if item.get('kind') not in ('main', 'side', 'drink', 'dessert', 'unknown'):
            raise ValueError('餐品分类无效')
        if item.get('menu_fen') is not None:
            cents(item['menu_fen'])
        kcal = item.get('kcal')
        if kcal is not None and (isinstance(kcal, bool) or not isinstance(kcal, (int, float)) or not math.isfinite(kcal) or kcal < 0):
            raise ValueError('热量必须是每份非负有限数值或 null')
        if item.get('selectable') is True and not item.get('evidence'):
            raise ValueError('可抽取餐品需要在售、分类及已选规格的来源说明')
    return snapshot


def single_person_sample(pool, count, no_main, rng):
    """Uniform subsets under main preference and at most one drink/dessert each."""
    groups = [[i for i in pool if i['kind'] == kind] for kind in ('main', 'side', 'drink', 'dessert')]
    weights = []
    for mains in range(0 if no_main else 1, min(count, len(groups[0])) + 1):
        for drinks in range(min(1, count, len(groups[2])) + 1):
            for desserts in range(min(1, count, len(groups[3])) + 1):
                sides = count - mains - drinks - desserts
                if not 0 <= sides <= len(groups[1]) or (no_main and mains) or mains + sides + desserts < 1:
                    continue
                sizes = (mains, sides, drinks, desserts)
                weight = math.prod(math.comb(len(group), size) for group, size in zip(groups, sizes))
                weights.append((sizes, weight))
    if not weights:
        raise ValueError('当前餐品不足以满足单人餐规则：饮品和甜品各最多1份；请减少数量或更换门店')
    ticket = rng.randrange(sum(weight for _, weight in weights))
    for sizes, weight in weights:
        if ticket < weight:
            selected = [item for group, size in zip(groups, sizes) for item in rng.sample(group, size)]
            rng.shuffle(selected)
            return selected
        ticket -= weight
    raise AssertionError('unreachable sampling ticket')


def draw(snapshot, no_main=False, count=3, seed=None):
    validate_snapshot(snapshot)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 6:
        raise ValueError('每次推荐 1 至 6 样，默认 3 样')
    if seed is not None and snapshot['mode'] != 'demo':
        raise ValueError('固定种子仅用于演示和测试；真实推荐使用系统随机数')
    pool = [item for item in snapshot['items'] if item.get('selectable') is True and item['kind'] != 'unknown']
    if no_main:
        pool = [item for item in pool if item['kind'] != 'main']
    selected = single_person_sample(pool, count, no_main, random.Random(seed) if seed is not None else random.SystemRandom())
    missing = [item['name'] for item in selected if item.get('kcal') is None]
    menu_known = all(item.get('menu_fen') is not None for item in selected)
    result = {
        'mode': snapshot['mode'], 'source': snapshot['source'], 'observed_at': snapshot['observed_at'],
        'store': snapshot['store'], 'context': snapshot['context'], 'no_main': no_main,
        'items': selected, 'basket': dict(Counter(item['id'] for item in selected)),
        'nutrition': {'known_kcal': round(sum(item.get('kcal') or 0 for item in selected), 2),
                      'complete': not missing, 'missing': missing},
        'menu_total_fen': sum(item['menu_fen'] for item in selected) if menu_known else None,
        'random_policy': '单人餐：饮品与甜品各最多1份、至少一份食物；等概率抽取符合条件的不同餐品组合，不按价格或热量加权',
        'snapshot_id': fingerprint(snapshot),
    }
    result['draw_id'] = fingerprint(result)
    return result


def optimize(meal, catalog, max_plans=24):
    """Enumerate exact covers; prices must be whole-order quotes, never coupon arithmetic."""
    validate_draw(meal)
    if catalog.get('draw_id') != meal['draw_id'] or catalog.get('mode') != meal['mode']:
        raise ValueError('优惠候选必须绑定本次抽取和相同数据模式')
    if catalog.get('store') != meal['store'] or catalog.get('context') != meal['context']:
        raise ValueError('优惠候选的门店或取餐场景与本次推荐不一致')
    offers = catalog.get('offers', [])
    if not 0 < len(offers) <= 40:
        raise ValueError('每轮支持 1 至 40 个已核实购买选项')
    target = Counter(meal['basket'])
    eligible = []
    seen = set()
    for offer in offers:
        if not offer.get('id') or offer['id'] in seen:
            raise ValueError('购买选项编码必须唯一')
        seen.add(offer['id'])
        cover = offer.get('covers', {})
        if not cover or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in cover.values()):
            raise ValueError('购买选项的餐品份数必须是正整数')
        if not offer.get('evidence') or not offer.get('label'):
            raise ValueError('购买选项需要真实组成及优惠条件说明')
        if Counter(cover) <= target:
            eligible.append(offer)
    plans = []
    truncated = False
    visits = 0
    # Combinations are bounded by a maximum six-item basket and forty offers.
    def search(start, remaining, chosen, groups):
        nonlocal truncated, visits
        visits += 1
        if visits > 20000:
            truncated = True
            return
        if not remaining:
            if len(plans) >= max_plans:
                truncated = True
                return
            ids = [offer['id'] for offer in chosen]
            plans.append({'id': fingerprint([meal['draw_id'], ids])[:20],
                          'offer_ids': ids, 'labels': [o['label'] for o in chosen],
                          'conditions': [o.get('conditions', '无额外条件') for o in chosen],
                          'offers': chosen})
            return
        for index in range(start, len(eligible)):
            if truncated:
                return
            offer = eligible[index]
            cover = Counter(offer['covers'])
            exclusive = set(offer.get('exclusive_groups', []))
            if cover <= remaining and not exclusive.intersection(groups):
                search(index+1, remaining-cover, chosen+[offer], groups | exclusive)
    search(0, target, [], set())
    return {'draw_id': meal['draw_id'], 'mode': meal['mode'], 'store': meal['store'],
            'context': meal['context'], 'plans': plans, 'truncated': truncated,
            'offer_count': len(eligible), 'scope': catalog.get('scope', '本轮已收集的等价购买选项')}


def select_best(meal, plans, quotes):
    validate_draw(meal)
    if plans['draw_id'] != meal['draw_id']:
        raise ValueError('餐单已改变，需要重新生成方案和核价')
    if plans['mode'] != meal['mode'] or plans['store'] != meal['store'] or plans['context'] != meal['context']:
        raise ValueError('购买方案的数据模式、门店或场景不一致')
    for plan in plans['plans']:
        cover = Counter()
        for offer in plan['offers']:
            cover.update(offer['covers'])
        if cover != Counter(meal['basket']):
            raise ValueError('购买方案更改了本次餐品或数量')
    valid, failed = [], []
    ids = {plan['id']: plan for plan in plans['plans']}
    seen = set()
    for quote in quotes:
        plan_id = quote.get('plan_id')
        if plan_id not in ids or plan_id in seen:
            raise ValueError('报价对应未知方案或重复方案')
        seen.add(plan_id)
        if quote.get('draw_id') != meal['draw_id'] or quote.get('mode') != meal['mode']:
            raise ValueError('报价已失效或混用了演示与真实数据')
        if quote.get('status') != 'success':
            failed.append({'plan_id': plan_id, 'reason': quote.get('reason', '官方核价未成功')})
            continue
        if not quote.get('quoted_at') or not quote.get('source'):
            raise ValueError('报价缺少来源或核价时间')
        amount = cents(quote['payable_fen'])
        valid.append({'plan_id': plan_id, 'payable_fen': amount, 'quoted_at': quote['quoted_at'],
                      'source': quote['source'], 'labels': ids[plan_id]['labels'],
                      'conditions': ids[plan_id]['conditions']})
    valid.sort(key=lambda q: (q['payable_fen'], q['plan_id']))
    baseline = next((q['payable_fen'] for q in valid if all(o.startswith('single:') for o in ids[q['plan_id']]['offer_ids'])), None)
    pending = [key for key in ids if key not in seen]
    return {'best': valid[0] if valid else None, 'quotes': valid, 'failed': failed,
            'baseline_fen': baseline, 'savings_fen': baseline-valid[0]['payable_fen'] if baseline is not None else None,
            'pending': pending, 'truncated': plans['truncated'], 'scope': plans['scope'],
            'conclusion': '本轮成功核价方案中的最低价' if valid else '尚无成功核价，无法确认到手价'}


def amount_to_fen(value, unit):
    if isinstance(value, bool) or unit not in ('fen', 'yuan'):
        raise ValueError('核价金额或单位无效')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('核价金额无效') from None
    if not number.is_finite() or number < 0:
        raise ValueError('核价金额无效')
    scaled = number * (100 if unit == 'yuan' else 1)
    rounded = scaled.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    if scaled != rounded:
        raise ValueError('核价精度超过人民币分，请检查金额单位')
    return int(rounded)
