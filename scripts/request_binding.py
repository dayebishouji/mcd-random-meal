"""Request binding adapted from mcd-budget-meal under MIT.
Copyright (c) 2026 mcd-budget-meal contributors.
Source revision: 25d5f345862186e9a181339118051cd4418a97e6.
See third_party/mcd-budget-meal-LICENSE and THIRD_PARTY_NOTICES.md.
"""

from collections import Counter
from meal import fingerprint

def text_value(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} 必须是大于等于 {minimum} 的整数")
    return value


def request_contents(arguments):
    """Read actual codes and quantities from a fully specified official request.

    Combo parents are limited to quantity=1: multiple-parent round quantity
    semantics have not been live verified. Standalone quantities may exceed one.
    """
    requested = arguments.get("items")
    if not isinstance(requested, list) or not requested:
        raise ValueError("核价 arguments.items 必须是非空数组")
    result = []
    for product in requested:
        if not isinstance(product, dict):
            raise ValueError("核价商品必须是对象")
        code = text_value(product.get("productCode"), "productCode")
        quantity = integer(product.get("quantity"), "quantity", 1)
        rounds = product.get("roundList")
        option = {"parent_modification": {}, "modification": product.get("modification", {})}
        if rounds is None:
            result.append((code, quantity, False, option))
            continue
        if quantity != 1:
            raise ValueError("批量入口暂只支持每个套餐父项 quantity=1；多份套餐需另行核实数量契约")
        if not isinstance(rounds, list) or not rounds:
            raise ValueError("套餐 roundList 需要完整的非空轮次数组")
        result.append((code, quantity, True, option))
        seen_rounds = set()
        for round_item in rounds:
            if not isinstance(round_item, dict):
                raise ValueError("套餐轮次必须是对象")
            round_code = text_value(round_item.get("round"), "round")
            if round_code in seen_rounds:
                raise ValueError("套餐轮次重复")
            seen_rounds.add(round_code)
            choices = round_item.get("comboItemList")
            if not isinstance(choices, list) or not choices:
                raise ValueError("每个套餐轮次需要实际已选子项")
            for choice in choices:
                if not isinstance(choice, dict):
                    raise ValueError("套餐子项必须是对象")
                result.append((text_value(choice.get("code"), "comboItemList.code"),
                               integer(choice.get("quantity"), "comboItemList.quantity", 1), False,
                               {"parent_modification": product.get("modification", {}),
                                "modification": choice.get("modification", {})}))
    return result


def physical_contents(items):
    """Physical codes, quantities and options; combo parents are not extra food."""
    result = Counter()
    for code, quantity, container, option in request_contents({'items': items}):
        if not container:
            result[(code, fingerprint(option))] += quantity
    return result


def same_contents(first, second):
    return physical_contents(first) == physical_contents(second)



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
