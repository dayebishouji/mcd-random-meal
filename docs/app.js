(function (root) {
  'use strict';
  function randomInt(max) {
    const range = 0x100000000;
    const limit = Math.floor(range / max) * max;
    const buffer = new Uint32Array(1);
    do { root.crypto.getRandomValues(buffer); } while (buffer[0] >= limit);
    return buffer[0] % max;
  }
  function draw(data, noMain = false, choose = randomInt) {
    if (data.mode !== 'demo') throw new Error('网页只接受明确标注的模拟数据');
    const pool = data.items.filter(i => i.selectable && i.kind !== 'unknown' && (!noMain || i.kind !== 'main'));
    const baskets = [];
    for (let a = 0; a < pool.length; a++) for (let b = a + 1; b < pool.length; b++) for (let c = b + 1; c < pool.length; c++) {
      const basket = [pool[a], pool[b], pool[c]];
      if (noMain ? basket.some(i => i.kind !== 'drink') : basket.some(i => i.kind === 'main')) baskets.push(basket);
    }
    if (!baskets.length) throw new Error('当前模拟餐品不足三样');
    const selected = baskets[choose(baskets.length)].slice();
    for (let i = selected.length - 1; i > 0; i--) { const j = choose(i + 1); [selected[i], selected[j]] = [selected[j], selected[i]]; }
    return selected;
  }
  function compare(data, selected) {
    const target = Object.fromEntries(selected.map(i => [i.id, 1]));
    const offers = data.offers.filter(o => Object.entries(o.covers).every(([id, count]) => count > 0 && count <= (target[id] || 0)));
    const plans = []; let truncated = false;
    function search(start, remaining, chosen, groups) {
      if (Object.values(remaining).every(n => n === 0)) {
        if (plans.length >= 24) { truncated = true; return; }
        plans.push({ offers: chosen, amount: chosen.reduce((sum, o) => sum + o.demo_fen, 0), labels: chosen.map(o => o.label) });
        return;
      }
      for (let index = start; index < offers.length && !truncated; index++) {
        const offer = offers[index], exclusive = offer.exclusive_groups || [];
        if (exclusive.some(g => groups.has(g)) || !Object.entries(offer.covers).every(([id, n]) => n <= (remaining[id] || 0))) continue;
        const next = { ...remaining };
        for (const [id, n] of Object.entries(offer.covers)) next[id] -= n;
        search(index + 1, next, [...chosen, offer], new Set([...groups, ...exclusive]));
      }
    }
    search(0, target, [], new Set());
    plans.sort((a, b) => a.amount - b.amount || a.labels.join('').localeCompare(b.labels.join(''), 'zh-CN'));
    const baseline = plans.find(p => p.offers.every(o => o.id.startsWith('single:')));
    return { plans, best: plans[0] || null, baseline: baseline ? baseline.amount : null, truncated };
  }
  const api = { draw, compare };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.MealDemo = api;
  if (typeof document === 'undefined') return;

  const data = root.MEAL_DEMO_DATA;
  const $ = id => document.getElementById(id);
  const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const money = fen => `¥${(fen / 100).toFixed(2)}`;
  const names = { main: '主食', side: '小食', drink: '饮品', dessert: '甜品' };
  const icons = { burger: '🍔', 'chicken-burger': '🍔', 'fish-burger': '🍔', wrap: '🌯', fries: '🍟', nuggets: '🍗', corn: '🌽', wings: '🍗', cola: '🥤', zero: '🥤', tea: '☕', pie: '🥧', icecream: '🍦' };
  const colors = { main: '#ffd43b', side: '#e5bda0', drink: '#d9e8b5', dessert: '#edb8b2' };
  let noMain = false, count = 0, selected = [], comparison;
  function show(items, example = false) {
    selected = items; comparison = compare(data, items);
    $('food-cards').innerHTML = items.map(i => `<article class="food-card" data-kind="${escape(i.kind)}"><div class="food-visual" style="--card-bg:${colors[i.kind]}"><small class="food-kind">${names[i.kind]}</small><span aria-hidden="true">${icons[i.id] || '🍽️'}</span></div><div class="food-info"><h3>${escape(i.name.replace(/^演示/, ''))}</h3><div class="food-stats"><b>${money(i.menu_fen)}</b><span>${i.kcal == null ? '热量未知' : `${i.kcal} <small>kcal</small>`}</span></div></div></article>`).join('');
    $('draw-status').textContent = example ? '固定模拟案例 · 不是随机结果' : `第 ${count} 次抽取 · ${noMain ? '不含主食' : '至少一份主食'}`;
    $('receipt-lines').innerHTML = items.map(i => `<div class="receipt-item"><span>${escape(i.name.replace(/^演示/, ''))} × 1</span><span>${money(i.menu_fen)}</span></div>`).join('');
    $('best-price').textContent = comparison.best ? money(comparison.best.amount) : '待计算';
    $('saving').textContent = comparison.best && comparison.baseline != null ? money(comparison.baseline - comparison.best.amount) : '无对照';
    const complete = items.every(i => i.kcal != null);
    $('total-kcal').textContent = `${items.reduce((sum, i) => sum + (i.kcal || 0), 0)} kcal${complete ? '' : '（仅已知部分）'}`;
    $('best-label').textContent = comparison.best ? `模拟买法：${comparison.best.labels.map(s => s.replaceAll('演示', '')).join(' ＋ ')}。仅比较已收集方案${comparison.truncated ? '，本轮方案已截断' : ''}；一单最多一张模拟券。` : '本轮没有可比较方案。';
    $('quote-count').textContent = `${comparison.plans.length} 份`;
    $('quote-list').innerHTML = comparison.plans.map(p => `<div class="quote-row"><span>${escape(p.labels.map(s => s.replaceAll('演示', '')).join(' ＋ '))}</span><b>${money(p.amount)}</b></div>`).join('');
    $('quote-details').open = false;
    $('store-name').textContent = data.store.name;
    $('store-address').textContent = data.store.address;
    $('copy-status').textContent = '';
    document.querySelector('.workspace').classList.remove('dealing');
    void document.querySelector('.workspace').offsetWidth;
    document.querySelector('.workspace').classList.add('dealing');
  }
  function redraw() { count++; show(draw(data, noMain)); }
  function setMode(value) {
    noMain = value;
    $('with-main').setAttribute('aria-pressed', String(!value));
    $('without-main').setAttribute('aria-pressed', String(value));
    $('with-main').classList.toggle('active', !value);
    $('without-main').classList.toggle('active', value);
    redraw();
  }
  $('draw-button').addEventListener('click', redraw);
  $('hero-draw').addEventListener('click', redraw);
  $('with-main').addEventListener('click', () => setMode(false));
  $('without-main').addEventListener('click', () => setMode(true));
  $('example-button').addEventListener('click', () => {
    noMain = false;
    $('with-main').setAttribute('aria-pressed', 'true'); $('without-main').setAttribute('aria-pressed', 'false');
    $('with-main').classList.add('active'); $('without-main').classList.remove('active');
    show(['burger', 'fries', 'cola'].map(id => data.items.find(i => i.id === id)), true);
  });
  $('copy-button').addEventListener('click', async () => {
    const text = `听天由麦｜模拟餐单\n${selected.map(i => `${i.name} × 1`).join('\n')}\n模拟最低价：${money(comparison.best.amount)}\n${$('total-kcal').textContent}\n${data.store.name}，${data.store.address}\n全部为虚构演示，不可用于下单。\nhttps://github.com/dayebishouji/mcd-random-meal`;
    try { await navigator.clipboard.writeText(text); $('copy-status').textContent = '模拟餐单已复制。'; }
    catch (_) { $('copy-status').textContent = '浏览器未允许复制，可直接选中餐单文字复制。'; }
  });
  redraw();
})(typeof globalThis !== 'undefined' ? globalThis : this);
