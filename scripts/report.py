"""Self-contained, escaped HTML reports. No network requests or credentials."""

from html import escape
from images import official_image


def money(value):
    return '待核价' if value is None else f'¥{value / 100:.2f}'


def render(result):
    meal, comparison = result['meal'], result.get('comparison', {})
    best = comparison.get('best')
    demo = meal['mode'] == 'demo'
    badge = '离线模拟 · 非实际价格 / 地址 / 热量' if demo else '真实 MCP 查询快照 · 购买前请重新核价'
    nutrition = meal['nutrition']
    kcal = f"{nutrition['known_kcal']:g}" + ('' if nutrition['complete'] else '+')
    cards = []
    kinds = {'main': '主食', 'side': '小食', 'drink': '饮品', 'dessert': '甜品'}
    for index, item in enumerate(meal['items'], 1):
        energy = '热量未知' if item.get('kcal') is None else f"{item['kcal']:g} kcal"
        image = official_image(item.get('image_url'))
        picture = f'<div class="product-image"><span>餐品图片暂缺</span><img src="{escape(image)}" alt="{escape(item["name"])}官方菜单示意图" loading="lazy" referrerpolicy="no-referrer" onerror="this.hidden=true"></div>' if image else ''
        cards.append(f'<article>{picture}<span class="number">0{index}</span><small>{escape(kinds.get(item["kind"], "餐品"))}</small><h2>{escape(item["name"])}</h2><p>{escape(energy)}</p><span>菜单参考价 {money(item.get("menu_fen"))}</span></article>')
    rows = ''.join(f'<tr><td>{escape(" + ".join(q["labels"]))}</td><td>{money(q["payable_fen"])}</td><td>{escape("；".join(q["conditions"]))}</td></tr>' for q in comparison.get('quotes', []))
    failure_count = len(comparison.get('failed', [])) + len(comparison.get('pending', []))
    limit = '；方案数量达到本轮上限' if comparison.get('truncated') else ''
    note = ('全部餐品已匹配每份热量。' if nutrition['complete'] else '以下餐品热量未知，总计仅含已知部分：' + '、'.join(nutrition['missing']))
    offer = ' + '.join(best['labels']) if best else '尚无成功核价方案'
    savings = '较本轮单点核价节省 ' + money(comparison['savings_fen']) if comparison.get('savings_fen') is not None else '未取得单点对照核价，暂不计算节省金额'
    store = meal['store']
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>听天由麦 · 随机餐单</title><style>
:root{{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#252018;background:#f6f2e9}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1050px;margin:auto;padding:40px 24px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid;padding-bottom:18px}}.brand{{font-size:20px;font-weight:800}}.badge{{font-size:12px;background:#ffe27b;padding:9px 12px;border-radius:4px}}h1{{font-size:clamp(35px,6vw,68px);letter-spacing:-2px;margin:40px 0 12px;line-height:1.15}}.intro{{color:#655b4e;line-height:1.8}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:30px 0}}article{{background:white;padding:24px;min-height:210px;border:1px solid #e3dacb;border-top:5px solid #d44029}}article small{{display:block;color:#746c62}}article h2{{font-size:22px;line-height:1.5}}article p{{font-size:21px;font-weight:700}}article span{{font-size:12px;color:#746c62}}.number{{float:right;color:#d44029;font-weight:800}}.summary{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#d7cebd;border:1px solid #d7cebd}}.metric{{padding:25px;background:#fff9e8}}.metric strong{{display:block;font-size:42px;margin-top:10px}}.metric small{{color:#746c62}}.store{{padding:24px 0;border-bottom:1px solid #d7cebd;line-height:1.8}}.store b{{font-size:19px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;border-bottom:1px solid #d7cebd;padding:15px 8px;line-height:1.6}}td:nth-child(2){{white-space:nowrap;font-weight:700}}.fine{{font-size:12px;color:#746c62;line-height:1.9}}section{{margin-top:32px}}footer{{margin-top:35px;border-top:2px solid;padding-top:20px}}@media(max-width:650px){{main{{padding:22px 16px}}header{{align-items:flex-start;gap:16px;flex-direction:column}}.cards{{grid-template-columns:1fr}}article{{min-height:0}}.summary{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style><main><header><span class="brand">听天由麦 / RANDOM MEAL</span><span class="badge">{badge}</span></header>
<style>.product-image{{height:160px;position:relative;margin:-5px 0 20px;display:grid;place-items:center}}.product-image>span{{font-size:12px;color:#655b4e}}.product-image img{{position:absolute;width:100%;height:100%;object-fit:contain;background:white}}.product-image img[hidden]{{display:none}}</style>
<h1>这一餐，随机决定。</h1><p class="intro">本轮 {len(meal['items'])} 样 · {'不要主食 · 已排除汉堡、卷、饭、面、三明治等主食' if meal['no_main'] else '默认带主食 · 至少抽中一份主食'}<br>先随机选餐，再为同一份餐单比较购买方式。</p>
<div class="cards">{''.join(cards)}</div><div class="summary"><div class="metric">{'演示最低报价' if demo else '本轮最低核价'}<strong>{money(best['payable_fen'] if best else None)}</strong><small>{escape(offer)}<br>{escape(savings)}</small></div><div class="metric">{'模拟' if demo else '已知'}总热量<strong>{kcal} <small>kcal</small></strong><small>{escape(note)}</small></div></div>
<div class="store"><b>{escape(store['name'])}</b><br>{escape(store['address'])}<br><span class="fine">到店取餐 · 数据时间 {escape(meal['observed_at'])}</span></div>
<section><h2>同样的餐品，比较怎么买</h2><p class="fine">{escape(comparison.get('conclusion', '尚未核价'))}。比较范围：{escape(comparison.get('scope', '尚未收集'))}{limit}。失败或待核价方案 {failure_count} 份。</p><table><thead><tr><th>购买组合</th><th>整单金额</th><th>使用条件</th></tr></thead><tbody>{rows or '<tr><td colspan="3">暂时没有成功核价结果，菜单参考价不能代替实付价。</td></tr>'}</tbody></table></section>
<footer class="fine">{escape(meal['random_policy'])}<br>随机结果可能重复；重新抽取会改变餐单，需要重新核价。热量缺失不当作零；不根据未知配方估算热量。<br>餐品图按官方菜单返回的地址引用，权利归麦当劳及相关权利人；图片仅作示意，实际规格以文字为准，图片加载可能需要联网。<br>个人原创参赛作品，非麦当劳官方产品。{'此页的门店、价格、热量与优惠为虚构演示，不可用于下单。' if demo else '本页记录当次查询结果，非持续更新的实时菜单。'}</footer></main></html>'''
