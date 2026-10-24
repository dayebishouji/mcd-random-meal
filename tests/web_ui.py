"""Browser regression checks. Requires Playwright and a local docs/ HTTP server.

python tests/web_ui.py --url http://127.0.0.1:8765
Optional: --browser-path /path/to/edge --screenshots /output/folder
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run(args):
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **({'executable_path': args.browser_path} if args.browser_path else {}))
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        context.on('page', lambda tab: tab.on('pageerror', lambda error: errors.append(str(error))))
        page.on('pageerror', lambda error: errors.append(str(error)))

        def ready():
            expect(page.locator('.workspace')).to_have_attribute('aria-busy', 'false')

        def ids():
            return page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).current.ids')

        page.goto(args.url)
        page.wait_for_load_state('networkidle')
        expect(page.locator('.food-card')).to_have_count(3)
        assert page.locator('.food-card[data-kind="main"]').count() >= 1
        assert page.locator('.hero-art img').evaluate('(img) => img.complete && img.naturalWidth > 0')
        checks.append('initial meal and illustration')

        # Dispatch a burst in the same frame, even after the control is disabled.
        before = page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).count')
        page.evaluate('for(let n=0;n<20;n++) document.querySelector("#draw-button").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
        expect(page.locator('.workspace')).to_have_attribute('aria-busy', 'true')
        expect(page.locator('#without-main')).to_be_disabled()
        ready()
        assert page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).count') == before + 1
        checks.append('20 rapid clicks produce exactly one draw')

        page.locator('#draw-button').click()
        page.evaluate('location.hash="meal=burger,fries,cola&noMain=0&example=1"')
        ready()
        expect(page.locator('#draw-status')).to_contain_text('固定模拟案例')
        expect(page.locator('#best-price')).to_have_text('¥29.00')
        checks.append('shared hash navigation during a draw')

        page.locator('#without-main').focus()
        page.keyboard.press('Space')
        ready()
        expect(page.locator('#without-main')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.food-card[data-kind="main"]')).to_have_count(0)
        no_main_ids = ids()
        page.locator('#share-button').click()
        expect(page.locator('#share-status')).to_contain_text('已复制')
        share_url = page.evaluate('navigator.clipboard.readText()')
        shared = context.new_page()
        shared.goto(share_url)
        shared.wait_for_load_state('networkidle')
        assert shared.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).current.ids') == no_main_ids
        expect(shared.locator('#draw-status')).to_contain_text('分享餐单')
        expect(shared.locator('.food-card[data-kind="main"]')).to_have_count(0)
        shared.close()
        page.reload()
        ready()
        assert ids() == no_main_ids
        checks.append('keyboard no-main, shared basket and refresh restoration')

        page.locator('#example-button').click()
        expect(page.locator('#best-price')).to_have_text('¥29.00')
        expect(page.locator('#saving')).to_have_text('¥19.00')
        expect(page.locator('#draw-status')).to_contain_text('固定模拟案例')
        page.locator('#quote-details summary').click()
        expect(page.locator('#quote-details')).to_have_attribute('open', '')
        page.locator('#budget-input').fill('20')
        page.locator('#kcal-input').fill('800')
        expect(page.locator('#budget-note')).to_contain_text('比预算多 ¥9.00')
        expect(page.locator('#budget-note')).to_contain_text('比热量参考多 145 kcal')
        page.locator('#budget-input').fill('40')
        page.locator('#kcal-input').fill('1000')
        expect(page.locator('#budget-note')).to_contain_text('预算内，余 ¥11.00')
        page.locator('#budget-input').fill('-1')
        expect(page.locator('#budget-input')).to_have_attribute('aria-invalid', 'true')
        expect(page.locator('#budget-note')).to_contain_text('请输入')
        page.locator('#budget-input').fill('1.001')
        expect(page.locator('#budget-input')).to_have_attribute('aria-invalid', 'true')
        page.locator('#budget-input').fill('40')
        page.locator('#kcal-input').fill('1.5')
        expect(page.locator('#kcal-input')).to_have_attribute('aria-invalid', 'true')
        page.locator('#kcal-input').fill('1000')
        page.reload()
        ready()
        expect(page.locator('#budget-input')).to_have_value('40')
        expect(page.locator('#kcal-input')).to_have_value('1000')
        expect(page.locator('#draw-status')).to_contain_text('固定模拟案例')
        checks.append('exact fixed quote, reference arithmetic, invalid input and preference persistence')

        page.locator('#share-button').click()
        expect(page.locator('#share-status')).to_contain_text('已复制')
        fixed_url = page.evaluate('navigator.clipboard.readText()')
        other_context = browser.new_context()
        other = other_context.new_page()
        other.goto(fixed_url)
        expect(other.locator('#draw-status')).to_contain_text('固定模拟案例')
        expect(other.locator('#best-price')).to_have_text('¥29.00')
        other_context.close()
        page.locator('#copy-button').click()
        expect(page.locator('#copy-status')).to_contain_text('已复制')
        copied = page.evaluate('navigator.clipboard.readText()')
        assert '固定模拟案例' in copied and '不可用于下单' in copied and '\n' in copied
        page.evaluate('Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async()=>{throw new Error("denied")}}})')
        page.locator('#share-button').click()
        expect(page.locator('#manual-copy')).to_be_visible()
        assert '#meal=' in page.locator('#manual-copy').input_value()
        expect(page.locator('#share-status')).to_contain_text('手动复制')
        checks.append('fixed-case sharing and clipboard rejection fallback')

        page.emulate_media(reduced_motion='reduce')
        for _ in range(10):
            page.locator('#draw-button').click()
            ready()
        assert 1 <= page.locator('.history-entry').count() <= 6
        page.locator('#example-button').click()
        page.locator('#without-main').click()
        ready()
        example = page.locator('.history-entry').filter(has_text='固定模拟案例')
        expect(example).to_have_count(1)
        example.click()
        expect(page.locator('#best-price')).to_have_text('¥29.00')
        expect(page.locator('#with-main')).to_have_attribute('aria-pressed', 'true')
        page.locator('#clear-history').click()
        expect(page.locator('.history-entry')).to_have_count(0)
        expect(page.locator('.history-empty')).to_be_visible()
        page.reload()
        expect(page.locator('.history-entry')).to_have_count(0)
        expect(page.locator('#best-price')).to_have_text('¥29.00')
        assert page.evaluate('getComputedStyle(document.documentElement).scrollBehavior') == 'auto'
        checks.append('bounded history, restore, clear and reduced motion')

        # All externally persisted IDs and hash input must be rejected safely.
        for fragment in ('#meal=burger,burger,cola&noMain=0', '#meal=burger,fries,cola&noMain=1', '#meal=missing,fries,cola&noMain=0', '#meal=%3Cscript%3E,fries,cola&noMain=0', '#meal=burger,fries,cola&noMain=0&example=1'):
            page.goto(args.url + fragment)
            expect(page.locator('.food-card')).to_have_count(3)
            if 'example=1' not in fragment:
                expect(page.locator('#action-status')).to_contain_text('链接无效')
        page.evaluate('localStorage.setItem("mcd-random-meal:v1","{corrupt")')
        page.goto(args.url)
        expect(page.locator('.food-card')).to_have_count(3)
        assert page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).current.ids.length') == 3
        checks.append('invalid and hostile links, damaged storage recovery')

        page.evaluate('globalThis.MEAL_DEMO_DATA.items.find(i=>i.id==="burger").kcal=null')
        page.locator('#example-button').click()
        page.locator('#kcal-input').fill('1000')
        expect(page.locator('#total-kcal')).to_contain_text('仅已知部分')
        expect(page.locator('#budget-note')).to_contain_text('热量未齐')
        page.evaluate('globalThis.MEAL_DEMO_DATA.offers=[]')
        page.locator('#example-button').click()
        expect(page.locator('#best-label')).to_contain_text('没有可比较方案')
        page.locator('#budget-input').fill('40')
        expect(page.locator('#budget-note')).to_contain_text('暂无报价')
        page.locator('#copy-button').click()
        expect(page.locator('#copy-status')).to_contain_text('已复制')
        assert '无可比较方案' in page.evaluate('navigator.clipboard.readText()')
        checks.append('unknown nutrition and empty offers')

        blocked = browser.new_context()
        blocked.add_init_script('Storage.prototype.getItem=()=>{throw new Error("blocked")};Storage.prototype.setItem=()=>{throw new Error("blocked")}')
        tab = blocked.new_page()
        tab.on('pageerror', lambda error: errors.append(str(error)))
        tab.goto(args.url)
        expect(tab.locator('#storage-note')).to_contain_text('未允许保存')
        tab.locator('#without-main').click()
        expect(tab.locator('.workspace')).to_have_attribute('aria-busy', 'false')
        expect(tab.locator('.food-card[data-kind="main"]')).to_have_count(0)
        blocked.close()
        checks.append('blocked browser storage remains usable')

        quota = browser.new_context()
        quota.add_init_script('Storage.prototype.setItem=()=>{throw new DOMException("Full","QuotaExceededError")}')
        tab = quota.new_page()
        tab.on('pageerror', lambda error: errors.append(str(error)))
        tab.goto(args.url)
        expect(tab.locator('#storage-note')).to_contain_text('未允许保存')
        expect(tab.locator('.food-card')).to_have_count(3)
        quota.close()
        checks.append('storage quota exceeded fallback')

        page.goto(args.url)
        page.emulate_media(reduced_motion='reduce')
        for no_main in (False, True):
            page.locator('#without-main' if no_main else '#with-main').click()
            ready()
            for quantity in range(1, 7):
                page.locator('#quantity-select').select_option(str(quantity))
                ready()
                expect(page.locator('.food-card')).to_have_count(quantity)
                assert len(set(ids())) == quantity
                assert page.locator('.food-card[data-kind="drink"]').count() <= 1
                assert page.locator('.food-card[data-kind="dessert"]').count() <= 1
                if quantity == 6:
                    assert page.locator('.food-card[data-kind="main"],.food-card[data-kind="side"]').count() >= 4
                if no_main:
                    expect(page.locator('.food-card[data-kind="main"]')).to_have_count(0)
                    assert page.locator('.food-card:not([data-kind="drink"])').count() >= 1
                else:
                    assert page.locator('.food-card[data-kind="main"]').count() == 1
                if quantity in (1, 6):
                    page.locator('#share-button').click()
                    expect(page.locator('#share-status')).to_contain_text('已复制')
                    link = page.evaluate('navigator.clipboard.readText()')
                    expected_ids = ids()
                    recipient = browser.new_context()
                    recipient_page = recipient.new_page()
                    recipient_page.goto(link)
                    expect(recipient_page.locator('.food-card')).to_have_count(quantity)
                    expect(recipient_page.locator('#quantity-select')).to_have_value(str(quantity))
                    assert recipient_page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).current.ids') == expected_ids
                    recipient.close()
        page.reload()
        expect(page.locator('#quantity-select')).to_have_value('6')
        expect(page.locator('.food-card')).to_have_count(6)
        checks.append('all 1–6 quantities in both modes; 1/6-item shares and refresh')

        for fragment in ('#meal=burger,cola,zero&noMain=0', '#meal=burger,pie,icecream&noMain=0', '#meal=burger,chicken-burger,fries&noMain=0'):
            page.goto(args.url+fragment)
            expect(page.locator('#action-status')).to_contain_text('链接无效')
        page.evaluate('''localStorage.setItem('mcd-random-meal:v1',JSON.stringify({current:{ids:['burger','fish-burger','fries','corn'],noMain:false},recent:[{ids:['burger','fish-burger','fries'],noMain:false}]}))''')
        page.goto(args.url)
        expect(page.locator('#quantity-select')).to_have_value('4')
        expect(page.locator('#action-status')).to_contain_text('旧餐单不符合')
        expect(page.locator('.food-card[data-kind="main"]')).to_have_count(1)
        assert page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).recent.every(entry=>MealDemo.validMeal(MEAL_DEMO_DATA,entry))')
        checks.append('multiple-main links and saved meals are rejected under the new rule')
        page.evaluate('''localStorage.setItem('mcd-random-meal:v1',JSON.stringify({current:{ids:['fries','nuggets','corn','cola','zero','tea'],noMain:true},recent:[{ids:['burger','cola','zero'],noMain:false}]}))''')
        page.goto(args.url)
        expect(page.locator('#quantity-select')).to_have_value('6')
        expect(page.locator('#without-main')).to_have_attribute('aria-pressed','true')
        expect(page.locator('#action-status')).to_contain_text('旧餐单不符合')
        assert page.locator('.food-card[data-kind="drink"]').count() <= 1
        assert page.locator('.food-card[data-kind="dessert"]').count() <= 1
        assert page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1")).recent.every(entry=>MealDemo.validMeal(MEAL_DEMO_DATA,entry))')
        checks.append('single-person caps reject old links and migrate invalid saved meals explicitly')

        page.evaluate('MEAL_DEMO_DATA.items.forEach(i=>i.selectable=["nuggets","corn"].includes(i.id))')
        page.locator('#quantity-select').select_option('5')
        ready()
        expect(page.locator('#action-status')).to_contain_text('可选餐品不足')
        expect(page.locator('#quantity-select')).to_be_enabled()
        page.locator('#quantity-select').select_option('2')
        ready()
        expect(page.locator('.food-card')).to_have_count(2)
        checks.append('insufficient eligible food keeps strict caps and allows smaller quantity recovery')

        missing_images = browser.new_context()
        missing_images.route('https://menu-img.mcd.cn/**', lambda route: route.abort())
        fallback = missing_images.new_page()
        fallback.on('pageerror', lambda error: errors.append(str(error)))
        fallback.goto(args.url)
        fallback.locator('#example-button').click()
        expect(fallback.locator('.image-credit').filter(has_text='图片暂缺')).to_have_count(3)
        expect(fallback.locator('.food-placeholder:visible')).to_have_count(3)
        expect(fallback.locator('#best-price')).to_have_text('¥29.00')
        missing_images.close()
        checks.append('official image failures keep usable placeholders and prices')

        page.goto(args.url+'#meal=burger,fries,cola&noMain=0&example=1')
        page.reload()
        before_state = page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
        page.evaluate('MEAL_DEMO_DATA.offers.find(o=>o.demo_fen===2900).demo_fen=2500')
        page.locator('#reprice-button').click()
        expect(page.locator('#best-price')).to_have_text('¥25.00')
        after_state = page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
        assert before_state['current'] == after_state['current'] and before_state['count'] == after_state['count'] and before_state['recent'] == after_state['recent']
        expect(page.locator('#draw-status')).to_contain_text('保留餐单')
        checks.append('reprice updates changed offers while preserving basket, draw count and history')

        page.locator('#external-panel summary').click()
        page.locator('#external-form button').click()
        expect(page.locator('#external-status')).to_contain_text('选择餐单内')
        expect(page.locator('#external-result')).to_be_hidden()
        page.locator('#external-items input[value="burger"]').check()
        page.locator('#external-items input[value="fries"]').check()
        page.locator('#external-extra').fill('2')
        page.locator('#external-form button').click()
        expect(page.locator('#external-result')).to_contain_text('¥23.00')
        expect(page.locator('#external-result')).to_contain_text('尚未核对')
        expect(page.locator('#best-price')).to_have_text('¥25.00')
        page.locator('#external-conditions').fill('<img src=x onerror=alert(1)>')
        expect(page.locator('#external-result')).to_be_hidden()
        page.locator('#external-confirm').check()
        page.locator('#external-form button').click()
        expect(page.locator('#external-result')).to_contain_text('未向平台验证')
        expect(page.locator('#external-result img')).to_have_count(0)
        page.locator('#external-items input[value="cola"]').check()
        page.locator('#external-form button').click()
        expect(page.locator('#external-result')).to_contain_text('¥15.00')
        expect(page.locator('#external-result')).to_contain_text('餐单已全部覆盖')
        checks.append('external voucher includes fees and whole remainder, stays separate, and escapes text')

        page.locator('#reprice-button').click()
        expect(page.locator('#external-items input:checked')).to_have_count(3)
        expect(page.locator('#external-result')).to_be_hidden()
        page.locator('#draw-button').click()
        ready()
        # A random draw may repeat the identical basket; force a different valid basket for this assertion.
        page.evaluate('location.hash="meal=corn,nuggets&noMain=1"')
        expect(page.locator('#food-cards .food-card')).to_have_count(2)
        expect(page.locator('#external-items input:checked')).to_have_count(0)
        expect(page.locator('#external-confirm')).not_to_be_checked()
        expect(page.locator('#external-result')).to_be_hidden()
        checks.append('repricing invalidates old reference; a different basket clears voucher coverage and confirmation')

        for value in ('-1','1.005','NaN','10000.01',''):
            assert page.evaluate('(value)=>{try{MealDemo.parseMoney(value);return false}catch(_){return true}}',value)
        assert page.evaluate('MealDemo.parseMoney("13.01")') == 1301
        page.evaluate('MEAL_DEMO_DATA.offers=[]')
        page.locator('#external-items input').first.check()
        page.locator('#external-form button').click()
        expect(page.locator('#external-result')).to_be_hidden()
        expect(page.locator('#external-status')).to_contain_text('余餐没有可比较')
        checks.append('external amount precision and missing remainder quote never produce a false low total')

        # One batched visual pass, alongside responsive checks.
        page.goto(args.url)
        page.reload()
        expect(page.locator('#catalog-note')).to_contain_text('42 样')
        page.locator('.catalog-panel summary').click()
        expect(page.locator('#catalog-list')).to_contain_text('板烧鸡腿堡')
        expect(page.locator('#bundle-reference-list .quote-row')).to_have_count(12)
        expect(page.locator('#bundle-reference-list')).to_contain_text('2026-10-24')
        page.locator('.catalog-panel summary').click()
        page.evaluate('location.hash="meal=mcd-1406,fries,mcd-521817&noMain=0"')
        expect(page.locator('#best-price')).to_have_text('¥35.50')
        expect(page.locator('#food-cards')).to_contain_text('板烧鸡腿堡')
        checks.append('expanded MCP food catalog, historical bundle quotes, and a new three-piece recipe')

        page.locator('#bundle-button').click()
        ready()
        expect(page.locator('#draw-status')).to_contain_text('套餐推荐')
        expect(page.locator('.food-card[data-kind="main"]')).to_have_count(1)
        expect(page.locator('.food-card')).to_have_count(3)
        page.locator('#without-main').click()
        ready()
        page.locator('#quantity-select').select_option('2')
        ready()
        page.locator('#bundle-button').click()
        ready()
        expect(page.locator('#draw-status')).to_contain_text('套餐推荐')
        expect(page.locator('.food-card[data-kind="main"]')).to_have_count(0)
        expect(page.locator('.food-card')).to_have_count(2)
        expect(page.locator('#best-price')).to_have_text('¥13.90')
        checks.append('explicit bundle mode obeys quantity and main preference, including no-main 1+1')

        page.locator('#quantity-select').select_option('6')
        ready()
        before_bundle=page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
        page.locator('#bundle-button').click()
        ready()
        expect(page.locator('#action-status')).to_contain_text('原餐单已保留')
        after_bundle=page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
        assert before_bundle==after_bundle
        checks.append('unsupported bundle count preserves the basket and does not silently relax constraints')
        page.locator('#with-main').click()
        ready()
        page.locator('#quantity-select').select_option('6')
        ready()
        page.locator('#external-panel summary').click()
        for width in (1440, 768, 390, 360, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            dimensions = page.evaluate('({viewport:innerWidth,content:document.documentElement.scrollWidth})')
            assert dimensions['content'] <= dimensions['viewport'], dimensions
            if args.screenshots and width in (1440, 390):
                output = Path(args.screenshots)
                output.mkdir(parents=True, exist_ok=True)
                page.locator('.demo-section').screenshot(path=str(output / f'updated-{width}.png'))
        checks.append('320/360/390/768/1440px responsive layouts')
        page.set_viewport_size({'width':1440,'height':1000})
        page.goto(args.url)
        page.keyboard.press('Tab')
        expect(page.locator('.skip-link')).to_be_focused()
        page.keyboard.press('Enter')
        assert page.url.endswith('#try')
        checks.append('keyboard skip navigation')
        assert not errors, errors
        browser.close()
    print(json.dumps({'checks': checks, 'page_errors': errors, 'result': 'passed'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--browser-path')
    parser.add_argument('--screenshots')
    run(parser.parse_args())
