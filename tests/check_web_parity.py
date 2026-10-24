"""Optional developer check: Node.js required, browser runtime has no dependencies."""
import copy
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from meal import draw, optimize


def main():
    node = shutil.which('node')
    if not node:
        raise SystemExit('此项开发检查需要安装 Node.js；运行网页和 Python Skill 不需要 Node.js。')
    cases = json.loads(subprocess.check_output([node, str(ROOT / 'tests/web_parity.cjs')], encoding='utf-8'))
    data = json.loads((ROOT / 'examples/demo.json').read_text(encoding='utf-8'))
    for case in cases:
        fixture = copy.deepcopy(data)
        fixture['items'] = [i for i in fixture['items'] if i['id'] in case['ids']]
        meal = draw(fixture, all(i['kind'] != 'main' for i in fixture['items']), seed=1)
        plans = optimize(meal, {**meal, 'offers': data['offers']})['plans']
        prices = [sum(o['demo_fen'] for o in p['offers']) for p in plans]
        baseline = next(sum(o['demo_fen'] for o in p['offers']) for p in plans if all(o['id'].startswith('single:') for o in p['offers']))
        assert case['best'] == min(prices) and case['baseline'] == baseline and case['count'] == len(plans), case
    print(f'网页/Python 金额对照通过：{len(cases)} 种不同的有效餐单')


if __name__ == '__main__':
    main()
