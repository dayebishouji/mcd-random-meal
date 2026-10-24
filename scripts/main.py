"""CLI entrypoint for a portable Agent Skill. Python 3.10+, no dependencies."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from meal import amount_to_fen, draw, optimize, select_best, validate_draw
from mcp_readonly import ALLOWED, MCP, ToolBusinessError, pointer, tool_data
from report import render
from external import compare_external
from request_binding import same_contents

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def demo(no_main=False, seed=None, count=3):
    snapshot = read(ROOT / 'examples' / 'demo.json')
    meal = draw(snapshot, no_main=no_main, seed=seed, count=count)
    return price_demo(meal)


def price_demo(meal, external=None):
    validate_draw(meal)
    if meal['mode'] != 'demo':
        raise ValueError('模拟核价只能用于明确标注的 demo 餐单')
    snapshot = read(ROOT / 'examples' / 'demo.json')
    catalog = {'draw_id': meal['draw_id'], 'mode': 'demo', 'store': meal['store'],
               'context': meal['context'], 'offers': snapshot['offers'],
               'scope': '虚构单点、等价套餐与演示券；不对应官方优惠'}
    plans = optimize(meal, catalog)
    quotes = [{'draw_id': meal['draw_id'], 'mode': 'demo', 'plan_id': p['id'], 'status': 'success',
               'payable_fen': sum(o['demo_fen'] for o in p['offers']),
               'quoted_at': snapshot['observed_at'], 'source': '虚构演示定价，非官方核价'}
              for p in plans['plans']]
    result = {'meal':meal,'comparison':select_best(meal,plans,quotes)}
    if external is not None:
        result['external_comparison'] = compare_external(meal,external,lambda remaining:price_demo(remaining)['comparison'])
    return result


def quote_requests(meal, plans, prepared, client, total_pointer, unit):
    validate_draw(meal)
    select_best(meal, plans, [])
    if meal['mode'] != 'live' or plans['mode'] != 'live':
        raise ValueError('真实核价只能用于 live 餐单')
    if prepared.get('draw_id') != meal['draw_id']:
        raise ValueError('核价请求未绑定本次随机餐单')
    supplied = prepared.get('requests', {})
    quotes = []
    for plan in plans['plans']:
        if plan['id'] not in supplied:
            continue
        arguments = supplied[plan['id']]
        if set(arguments) - ({'storeCode', 'items'} | set(meal['context'])):
            raise ValueError('核价请求包含餐单之外的附加字段')
        if arguments.get('storeCode') != meal['store']['id']:
            raise ValueError('核价请求门店与餐单不一致')
        for key, expected in meal['context'].items():
            if arguments.get(key) != expected:
                raise ValueError('核价请求取餐场景与餐单不一致')
        if not isinstance(arguments.get('items'), list) or not arguments['items']:
            raise ValueError('核价 items 必须是非空数组')
        # Each offer carries the exact schema-derived item payload used for the order.
        expected_items = [o['request_item'] for o in plan['offers']]
        if arguments['items'] != expected_items:
            raise ValueError('核价请求更改了已验证购买选项')
        selected_requests = [i.get('request_item') for i in meal['items']]
        if not all(selected_requests) or not same_contents(arguments['items'],selected_requests):
            raise ValueError('原餐单请求规格缺失，或套餐实际餐品、份数和特调与原餐单不一致')
        try:
            result = client.call('calculate-price', arguments)
            payload = tool_data(result)
            price = amount_to_fen(pointer(payload, total_pointer), unit)
        except ToolBusinessError as exc:
            quotes.append({'draw_id': meal['draw_id'], 'mode': 'live', 'plan_id': plan['id'],
                           'status': 'failed', 'reason': str(exc)})
            continue
        except (ValueError, KeyError, TypeError) as exc:
            quotes.append({'draw_id': meal['draw_id'], 'mode': 'live', 'plan_id': plan['id'],
                           'status': 'failed', 'reason': str(exc)})
            break
        quotes.append({'draw_id': meal['draw_id'], 'mode': 'live', 'plan_id': plan['id'],
                       'status': 'success', 'payable_fen': price,
                       'quoted_at': payload.get('datetime') or datetime.now(timezone.utc).isoformat(),
                       'source': '麦当劳 MCP calculate-price；' + total_pointer + '；单位 ' + unit})
    return quotes


def main():
    parser = argparse.ArgumentParser(description='听天由麦：随机选餐、计算热量、比较同餐单优惠')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('demo', help='运行明确标注的离线模拟')
    p.add_argument('--no-main', action='store_true')
    p.add_argument('--count', type=int, choices=range(1, 7), default=3, help='推荐数量 1–6，默认 3')
    p.add_argument('--seed', type=int, help='仅供演示复现，正常使用留空')
    p.add_argument('--output', default=str(ROOT / 'local' / 'demo.json'))
    p.add_argument('--html', default=str(ROOT / 'local' / 'demo.html'))
    p = commands.add_parser('draw', help='从宿主用 MCP 整理的菜单中随机抽餐')
    p.add_argument('--input', required=True)
    p.add_argument('--no-main', action='store_true')
    p.add_argument('--count', type=int, choices=range(1, 7), default=3)
    p.add_argument('--output', required=True)
    p = commands.add_parser('live', help='按指定城市地标查询、随机选餐并进行官方核价')
    p.add_argument('--bundle', action='store_true', help='显式套餐模式：从当前核验通过的单人套餐参考搭配中随机选餐')
    p.add_argument('--city', required=True)
    p.add_argument('--keyword', required=True)
    p.add_argument('--store-code', help='不填时选接口返回的首家营业门店')
    p.add_argument('--no-main', action='store_true')
    p.add_argument('--count', type=int, choices=range(1, 7), default=3, help='推荐数量 1–6，默认 3')
    p.add_argument('--output', default=str(ROOT / 'local' / 'live.json'))
    p.add_argument('--html', default=str(ROOT / 'local' / 'live.html'))
    p = commands.add_parser('reprice', help='保留原餐单，重新查询套餐、随心配与门店券并核价')
    p.add_argument('--input', default=str(ROOT / 'local' / 'live.json'), help='原推荐结果JSON或 draw.json')
    p.add_argument('--external-offers', help='用户提供的外部平台券价与覆盖范围JSON，只作参考比较')
    p.add_argument('--output', default=str(ROOT / 'local' / 'repriced.json'))
    p.add_argument('--html', default=str(ROOT / 'local' / 'repriced.html'))
    p = commands.add_parser('doctor', help='检查安装、环境变量和只读 MCP 连接')
    p.add_argument('--offline', action='store_true', help='仅检查安装和离线流程，不发网络请求')
    p.add_argument('--output', default=str(ROOT / 'local' / 'doctor.json'))
    p = commands.add_parser('plan', help='枚举保持餐品、规格和份数不变的购买方案')
    p.add_argument('--draw', required=True)
    p.add_argument('--catalog', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('compare', help='比较官方整单核价并生成报告')
    p.add_argument('--draw', required=True)
    p.add_argument('--plans', required=True)
    p.add_argument('--quotes', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--html')
    p = commands.add_parser('tools', help='发现实际 MCP schema，仅输出只读工具')
    p.add_argument('--output', required=True)
    p = commands.add_parser('call', help='按实际 schema 调用一个只读 MCP 工具')
    p.add_argument('tool', choices=sorted(ALLOWED))
    p.add_argument('--arguments', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('quote', help='通过官方 MCP 对已绑定的购买方案整单核价')
    p.add_argument('--draw', required=True)
    p.add_argument('--plans', required=True)
    p.add_argument('--requests', required=True)
    p.add_argument('--amount-pointer', default='/data/price')
    p.add_argument('--unit', choices=('fen', 'yuan'), default='fen')
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'demo':
        result = demo(args.no_main, args.seed, args.count)
    elif args.command == 'reprice':
        original = read(args.input)
        meal = original.get('meal',original)
        validate_draw(meal)
        external = read(args.external_offers) if args.external_offers else None
        if meal['mode'] == 'demo':
            result = price_demo(meal,external)
        else:
            from pricing import price_saved
            client = MCP()
            client.connect()
            result = price_saved(client,meal,external=external)
    elif args.command == 'doctor':
        import os
        token = os.environ.get('MCD_MCP_TOKEN', '').strip()
        demo(count=1)
        result = {'installation': 'passed', 'offline_demo': 'passed',
                  'token_configured': bool(token and not token.startswith('${')), 'connection': 'not_checked'}
        if not args.offline:
            client = MCP()
            client.connect()
            names = {tool['name'] for tool in client.tools()}
            required = {'query-nearby-stores', 'query-meals', 'query-meal-detail', 'list-nutrition-foods', 'query-store-coupons', 'calculate-price'}
            missing = sorted(required - names)
            if missing:
                raise ValueError('MCP 缺少所需只读工具：' + '、'.join(missing))
            result.update(connection='passed', required_tools='available', network_retries=client.retry_count)
    elif args.command == 'draw':
        result = draw(read(args.input), args.no_main, args.count)
    elif args.command == 'plan':
        result = optimize(read(args.draw), read(args.catalog))
    elif args.command == 'compare':
        meal = read(args.draw)
        result = {'meal': meal, 'comparison': select_best(meal, read(args.plans), read(args.quotes))}
    else:
        client = MCP()
        client.connect()
        if args.command == 'tools':
            result = client.tools()
        elif args.command == 'live':
            from live import live_recommend
            result = live_recommend(client, args.city, args.keyword, args.store_code, args.no_main, args.count, bundle_mode=args.bundle)
        elif args.command == 'call':
            result = client.call(args.tool, read(args.arguments))
        else:
            result = quote_requests(read(args.draw), read(args.plans), read(args.requests), client, args.amount_pointer, args.unit)
    write(args.output, result)
    if getattr(args, 'html', None):
        html_path = Path(args.html)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render(result), encoding='utf-8')
        print(str(html_path.resolve()))
    print(str(Path(args.output).resolve()))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError) as exc:
        raise SystemExit(f'本轮未完成：{exc}') from None
