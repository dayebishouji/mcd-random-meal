"""User-supplied voucher costs, kept separate from official whole-order quotes."""
import copy
from collections import Counter

from meal import cents, fingerprint, validate_draw


def remainder(meal, covers):
    result = copy.deepcopy(meal)
    result.pop('draw_id')
    result['items'] = [i for i in result['items'] if i['id'] not in covers]
    result['basket'] = {i['id']:1 for i in result['items']}
    missing = [i['name'] for i in result['items'] if i.get('kcal') is None]
    result['nutrition'] = {'known_kcal':round(sum(i.get('kcal') or 0 for i in result['items']),2), 'complete':not missing, 'missing':missing}
    result['menu_total_fen'] = sum(i['menu_fen'] for i in result['items']) if all(i.get('menu_fen') is not None for i in result['items']) else None
    result['random_policy'] = '固定餐单中未被外部券覆盖的余餐，非新抽取'
    result['draw_id'] = fingerprint(result)
    return result


def validate_external(meal, document):
    validate_draw(meal)
    if not isinstance(document,dict):
        raise ValueError('外部券文件必须是对象')
    if document.get('draw_id') != meal['draw_id'] or document.get('store_id') != meal['store']['id'] or document.get('context') != meal['context']:
        raise ValueError('外部券必须绑定同一餐单、门店和取餐场景')
    offers = document.get('offers')
    if not isinstance(offers,list) or not 1 <= len(offers) <= 4:
        raise ValueError('每轮支持1–4个外部券参考选项，分别比较，不自动叠加')
    checked, seen = [], set()
    for offer in offers:
        if not isinstance(offer,dict):
            raise ValueError('外部券必须是对象')
        for key in ('id','platform','label','conditions'):
            if not isinstance(offer.get(key),str) or not offer[key].strip() or len(offer[key]) > 500:
                raise ValueError('外部券必须提供名称、平台、使用条件和唯一编号')
        if offer['id'] in seen:
            raise ValueError('外部券编号重复')
        seen.add(offer['id'])
        covers = offer.get('covers')
        if not isinstance(covers,dict) or not covers or any(type(n) is not int or n != 1 for n in covers.values()) or not Counter(covers) <= Counter(meal['basket']):
            raise ValueError('外部券只能覆盖餐单中实际存在的相同规格和份数，不能加餐或换餐')
        if type(offer.get('confirmed')) is not bool:
            raise ValueError('必须明确外部券的适用条件是否已由用户核对')
        cost = cents(offer.get('purchase_fen')) + cents(offer.get('extra_fen'))
        checked.append((offer,cost))
    return checked


def compare_external(meal, document, quote_remaining):
    checked = validate_external(meal,document)
    results = []
    cache = {}
    for offer,cost in checked:
        remaining = remainder(meal,offer['covers'])
        key = tuple(sorted(remaining['basket']))
        if not key:
            comparison = {'best':{'payable_fen':0,'labels':[]},'pending':[],'failed':[],'truncated':False}
        else:
            if key not in cache:
                cache[key] = quote_remaining(remaining)
            comparison = cache[key]
        best = comparison.get('best')
        results.append({'id':offer['id'],'platform':offer['platform'],'label':offer['label'],
                        'covers':offer['covers'],'purchase_fen':offer['purchase_fen'],'extra_fen':offer['extra_fen'],
                        'remaining_names':[i['name'] for i in remaining['items']],
                        'remaining_fen':best['payable_fen'] if best else None,
                        'remaining_plan':best['labels'] if best else [],
                        'reference_total_fen':cost+best['payable_fen'] if best else None,
                        'confirmed':offer['confirmed'],'conditions':offer['conditions'],
                        'source':'券价与补差由用户提供；仅余餐使用本轮核价，合计不是官方整单实付',
                        'remaining_truncated':comparison.get('truncated',False),
                        'remaining_unquoted':len(comparison.get('pending',[]))+len(comparison.get('failed',[]))})
    results.sort(key=lambda value:(value['reference_total_fen'] is None,value['reference_total_fen'] or 0))
    return {'status':'user_reference_only','offers':results,'best':next((r for r in results if r['reference_total_fen'] is not None),None),
            'notice':'外部券需独立购买/核销，门店、时段、规格、限购及补差以券面为准；不保证能与官方订单叠加，不自动购券或领券'}
