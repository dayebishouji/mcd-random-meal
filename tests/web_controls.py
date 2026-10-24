"""Audit visible control feedback, navigation and mobile result discovery."""
import argparse
import json
from playwright.sync_api import sync_playwright, expect


def run(args):
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'executable_path': args.browser_path} if args.browser_path else {}))
        for width in (390, 1440):
            context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce', permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url, wait_until='networkidle')

            def ready():
                expect(page.locator('.workspace')).to_have_attribute('aria-busy', 'false')

            def in_view(selector):
                assert page.locator(selector).evaluate('(e)=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}'), selector

            page.locator('#example-button').click()
            ready()
            in_view('#draw-status')
            before = page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
            page.locator('#reprice-button').click()
            expect(page.locator('#reprice-status')).to_contain_text('¥29.00')
            in_view('#reprice-status')
            first = page.locator('#reprice-status').inner_text()
            page.locator('#reprice-button').click()
            assert page.locator('#reprice-status').inner_text() != first
            after = page.evaluate('JSON.parse(localStorage.getItem("mcd-random-meal:v1"))')
            assert before == after
            page.locator('#without-main').click()
            ready()
            expect(page.locator('#reprice-status')).to_be_empty()
            example = page.locator('.history-entry').filter(has_text='固定模拟案例')
            example.click()
            expect(page.locator('#best-price')).to_have_text('¥29.00')
            expect(page.locator('#draw-status')).to_be_focused()
            in_view('#draw-status')
            checks.append(f'{width}px: example/history locate results; repeated repricing has nearby feedback and preserves state')

            page.locator('#share-button').click()
            expect(page.locator('#share-status')).to_contain_text('已复制')
            shared_url = page.evaluate('navigator.clipboard.readText()')
            shared = context.new_page()
            shared.goto(shared_url, wait_until='networkidle')
            expect(shared.locator('#draw-status')).to_contain_text('固定模拟案例')
            assert shared.locator('#draw-status').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}')
            shared.close()
            page.locator('#copy-button').click()
            expect(page.locator('#copy-status')).to_contain_text('已复制')
            assert '¥29.00' in page.evaluate('navigator.clipboard.readText()')
            page.locator('#clear-history').click()
            expect(page.locator('.history-empty')).to_be_visible()
            expect(page.locator('#history-status')).to_contain_text('已清空')
            in_view('#history-status')
            expect(page.locator('#history-title')).to_be_focused()
            expect(page.locator('#clear-history')).to_be_disabled()
            checks.append(f'{width}px: share/copy, shared-link landing, history clearing and focus')

            for selector, content in [('.catalog-panel', '#catalog-list'), ('#quote-details', '#quote-list'), ('#external-panel', '#external-form')]:
                details = page.locator(selector)
                details.locator('summary').click()
                expect(page.locator(content)).to_be_visible()
                details.locator('summary').click()
                expect(page.locator(content)).to_be_hidden()
            page.locator('#external-panel summary').click()
            page.locator('#external-form button').click()
            expect(page.locator('#external-status')).to_contain_text('选择餐单内')
            for checkbox in page.locator('#external-items input').all():
                checkbox.check()
            page.locator('#external-platform').select_option('抖音')
            page.locator('#external-price').fill('13')
            page.locator('#external-extra').fill('2')
            page.locator('#external-confirm').check()
            page.locator('#external-conditions').fill('按券面适用规格')
            page.locator('#external-form button').click()
            expect(page.locator('#external-result')).to_contain_text('抖音券参考合计 ¥15.00')
            page.locator('#external-price').fill('-1')
            page.locator('#external-form button').click()
            expect(page.locator('#external-result')).to_be_hidden()
            expect(page.locator('#external-price')).to_be_focused()
            assert not page.locator('#external-price').evaluate('(e)=>e.validity.valid')
            page.locator('#external-price').fill('13')
            page.locator('#external-items input').first.uncheck()
            page.locator('#external-form button').click()
            expect(page.locator('#external-result')).to_be_visible()
            checks.append(f'{width}px: all expandable panels, platform/coverage/fees/confirmation/notes, invalid and corrected voucher submission')

            page.locator('#budget-input').fill('20')
            page.locator('#kcal-input').fill('800')
            expect(page.locator('#budget-note')).to_contain_text('比预算多')
            page.locator('#budget-input').fill('')
            page.locator('#kcal-input').fill('')
            expect(page.locator('#budget-note')).to_contain_text('未设参考值')
            page.locator('#hero-draw').click()
            ready()
            assert page.url.endswith('#try')
            if page.locator('.nav-proof').is_visible():
                page.locator('.nav-proof').click()
                assert page.url.endswith('#proof')
                in_view('#proof-title')
            page.locator('.footer-brand').click()
            assert page.evaluate('scrollY') == 0
            # Observe each external link's actual popup navigation without loading GitHub.
            context.route('https://github.com/**', lambda route: route.fulfill(status=200, body='<title>Navigation target</title>'))
            for link in page.locator('a[target="_blank"]').all():
                href = link.get_attribute('href')
                assert link.get_attribute('rel') == 'noopener noreferrer'
                with page.expect_popup() as opened:
                    link.click()
                popup = opened.value
                popup.wait_for_load_state()
                assert popup.url == href
                popup.close()
            page.locator('.topbar .brand').click()
            assert page.evaluate('scrollY') == 0
            checks.append(f'{width}px: budget/energy reset, hero draw, proof/home anchors and every GitHub popup')

            page.evaluate('MEAL_DEMO_DATA.offers=[]')
            page.locator('#reprice-button').click()
            expect(page.locator('#reprice-status')).to_contain_text('暂无可比较方案')
            page.locator('#quote-details summary').click()
            expect(page.locator('#quote-list')).to_contain_text('暂无可比较方案')
            checks.append(f'{width}px: empty quotes have an explicit result after repricing and expansion')
            assert not errors, errors
            context.close()
        browser.close()
    print(json.dumps({'checks': checks, 'result': 'passed'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--browser-path')
    run(parser.parse_args())
