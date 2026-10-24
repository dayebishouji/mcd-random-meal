(function (root) {
  'use strict';
  function randomInt(max) {
    const range = 0x100000000;
    const limit = Math.floor(range / max) * max;
    const buffer = new Uint32Array(1);
    do { root.crypto.getRandomValues(buffer); } while (buffer[0] >= limit);
    return buffer[0] % max;
  }
  function draw(data, noMain = false, choose = randomInt, quantity = 3) {
    if (data.mode !== 'demo') throw new Error('网页只接受明确标注的模拟数据');
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 6) throw new Error('每次推荐 1–6 样');
    const pool = data.items.filter(i => i.selectable && i.kind !== 'unknown' && (!noMain || i.kind !== 'main'));
    const baskets = [];
    function collect(start, basket) {
      if (basket.length === quantity) {
        const balanced = basket.filter(i => i.kind === 'drink').length <= 1 && basket.filter(i => i.kind === 'dessert').length <= 1;
        if (balanced && (noMain ? basket.some(i => i.kind !== 'drink') : basket.some(i => i.kind === 'main'))) baskets.push(basket);
        return;
      }
      for (let index = start; index <= pool.length - (quantity - basket.length); index++) collect(index + 1, [...basket, pool[index]]);
    }
    collect(0, []);
    if (!baskets.length) throw new Error('当前模拟餐品不足以满足数量和主食规则');
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
  function validMeal(data, value) {
    if (!value || !Array.isArray(value.ids) || value.ids.length < 1 || value.ids.length > 6 || new Set(value.ids).size !== value.ids.length || typeof value.noMain !== 'boolean') return false;
    const items = value.ids.map(id => data.items.find(i => i.id === id && i.selectable && i.kind !== 'unknown'));
    if (items.some(i => !i)) return false;
    if (items.filter(i => i.kind === 'drink').length > 1 || items.filter(i => i.kind === 'dessert').length > 1) return false;
    if (value.example === true && (value.noMain || value.ids.join(',') !== 'burger,fries,cola')) return false;
    return value.noMain ? items.every(i => i.kind !== 'main') && items.some(i => i.kind !== 'drink') : items.some(i => i.kind === 'main');
  }
  function officialImage(value) {
    if (typeof value !== 'string' || value.length > 2048) return null;
    try {
      const url = new URL(value);
      if (url.protocol === 'https:' && ['menu-img.mcd.cn', 'img.mcd.cn'].includes(url.hostname) && !url.username && !url.password && !url.port && !url.search && !url.hash) return url.href;
    } catch (_) { /* Missing or unsupported URLs use the existing placeholder. */ }
    return null;
  }
  const api = { draw, compare, validMeal, officialImage };
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
  const storageKey = 'mcd-random-meal:v1';
  let noMain = false, quantity = 3, count = 0, selected = [], comparison, busy = false, currentExample = false, renderVersion = 0;
  let recent = [], storageAvailable = true, saved = {}, storedText = null;
  try { storedText = root.localStorage.getItem(storageKey); }
  catch (_) { storageAvailable = false; }
  try { saved = JSON.parse(storedText || '{}') || {}; }
  catch (_) { saved = {}; }
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) saved = {};
  recent = (Array.isArray(saved.recent) ? saved.recent : []).filter(value => validMeal(data, value)).slice(0, 6);
  count = Number.isSafeInteger(saved.count) && saved.count >= 0 && saved.count < 1000000 ? saved.count : 0;
  function currentMeal() { return { ids: selected.map(i => i.id), noMain, example: currentExample }; }
  function storageNote() {
    $('storage-note').textContent = storageAvailable ? '最近 6 份餐单仅保存在此浏览器，点击即可恢复。' : '浏览器未允许保存记录；本次仍可抽取、恢复和分享，刷新后记录可能丢失。';
  }
  function persist() {
    if (!storageAvailable) return;
    try { root.localStorage.setItem(storageKey, JSON.stringify({ current: currentMeal(), recent, count, budget: $('budget-input').validity.valid ? $('budget-input').value : '', kcal: $('kcal-input').validity.valid ? $('kcal-input').value : '' })); }
    catch (_) { storageAvailable = false; storageNote(); }
  }
  function mode(value) {
    noMain = value;
    $('with-main').setAttribute('aria-pressed', String(!value));
    $('without-main').setAttribute('aria-pressed', String(value));
    $('with-main').classList.toggle('active', !value);
    $('without-main').classList.toggle('active', value);
  }
  function renderHistory() {
    $('history-list').innerHTML = recent.length ? recent.map((entry, index) => `<button class="history-entry" data-history="${index}"${busy ? ' disabled' : ''}><span>${entry.ids.map(id => escape(data.items.find(i => i.id === id).name.replace(/^演示/, ''))).join(' ＋ ')}</span><small>${entry.ids.length} 样 · ${entry.example ? '固定模拟案例' : entry.noMain ? '不含主食' : '带主食'} · 恢复 ↗</small></button>`).join('') : '<p class="history-empty">还没有记录。再抽一组，就会留在这里。</p>';
    $('clear-history').disabled = busy || recent.length === 0;
  }
  function updateReference() {
    const budget = $('budget-input'), kcal = $('kcal-input');
    for (const input of [budget, kcal]) input.setAttribute('aria-invalid', String(!input.validity.valid));
    const invalid = !budget.validity.valid || !kcal.validity.valid;
    const messages = [];
    if (invalid) messages.push('请输入 0–10000 的数值；预算最多两位小数，热量填整数。');
    else {
      if (budget.value !== '' && comparison?.best) {
        const difference = comparison.best.amount - Math.round(Number(budget.value) * 100);
        messages.push(difference > 0 ? `比预算多 ${money(difference)}` : `预算内，余 ${money(-difference)}`);
      } else if (budget.value !== '') messages.push('暂无报价，暂不判断预算');
      if (kcal.value !== '') {
        if (selected.some(i => i.kcal == null)) messages.push('热量未齐，暂不判断参考值');
        else { const difference = selected.reduce((sum, i) => sum + i.kcal, 0) - Number(kcal.value); messages.push(difference > 0 ? `比热量参考多 ${difference} kcal` : `热量参考内，余 ${-difference} kcal`); }
      }
    }
    $('budget-note').textContent = messages.join('；') || '未设参考值，放轻松抽。';
    $('budget-note').classList.toggle('input-error', invalid);
    return !invalid;
  }
  function show(items, source = 'random', remember = true) {
    selected = items; comparison = compare(data, items);
    quantity = items.length;
    $('quantity-select').value = String(quantity);
    $('quantity-hint').textContent = `${quantity} 样 · 饮品、甜品各最多 1 份`;
    $('food-cards').dataset.size = String(quantity);
    currentExample = source === 'example'; renderVersion++;
    $('food-cards').innerHTML = items.map(i => {
      const image = officialImage(i.image_url);
      return `<article class="food-card" data-kind="${escape(i.kind)}"><div class="food-visual" style="--card-bg:${colors[i.kind]}"><small class="food-kind">${names[i.kind]}</small><span class="food-placeholder" aria-hidden="true">${icons[i.id] || '🍽️'}</span>${image ? `<img class="product-photo" src="${escape(image)}" alt="${escape(i.image_caption || i.name)}" loading="lazy" referrerpolicy="no-referrer">` : ''}</div><div class="food-info"><h3>${escape(i.name.replace(/^演示/, ''))}</h3><div class="food-stats"><b>${money(i.menu_fen)}</b><span>${i.kcal == null ? '热量未知' : `${i.kcal} <small>kcal</small>`}</span></div>${image ? `<small class="image-credit">${escape(i.image_caption || '麦当劳官方菜单示意图')}</small>` : '<small class="image-credit">餐品示意占位图</small>'}</div></article>`;
    }).join('');
    document.querySelectorAll('.product-photo').forEach(image => {
      const loaded = () => image.parentElement.classList.add('has-photo');
      const failed = () => { image.parentElement.classList.remove('has-photo'); image.hidden = true; image.closest('.food-card').querySelector('.image-credit').textContent = '图片暂缺 · 使用示意占位图'; };
      image.addEventListener('load', loaded, { once: true });
      image.addEventListener('error', failed, { once: true });
      if (image.complete) { if (image.naturalWidth) loaded(); else failed(); }
    });
    $('draw-status').textContent = currentExample ? '固定模拟案例 · 不是随机结果' : source === 'random' ? `第 ${count} 次抽取 · ${noMain ? '不含主食' : '至少一份主食'}` : `${source === 'shared' ? '分享' : '恢复'}餐单 · 不是新抽取`;
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
    $('share-status').textContent = '';
    $('manual-copy').hidden = true;
    $('action-status').textContent = source === 'random' ? '开饭签已揭晓。看看手气，再看看账单。' : currentExample ? '已展示固定模拟案例，可展开小票比较买法。' : '已恢复同一份模拟餐单，价格按当前演示数据重算。';
    document.querySelector('.workspace').classList.remove('dealing');
    void document.querySelector('.workspace').offsetWidth;
    document.querySelector('.workspace').classList.add('dealing');
    if (remember) {
      const entry = currentMeal(), key = entry.ids.slice().sort().join(',');
      recent = [entry, ...recent.filter(value => value.ids.slice().sort().join(',') !== key)].slice(0, 6);
    }
    renderHistory(); updateReference(); persist();
  }
  function setBusy(value) {
    busy = value;
    document.querySelector('.workspace').setAttribute('aria-busy', String(value));
    document.querySelector('.demo-section').classList.toggle('is-drawing', value);
    for (const id of ['draw-button', 'with-main', 'without-main', 'quantity-select', 'example-button']) $(id).disabled = value;
    for (const id of ['copy-button', 'share-button']) $(id).disabled = value || !selected.length;
    $('hero-draw').setAttribute('aria-disabled', String(value));
    $('draw-button').setAttribute('aria-label', value ? '正在抽取餐单' : '再抽一组');
    renderHistory();
  }
  function redraw(nextMode = noMain, nextQuantity = quantity) {
    if (busy) return;
    const previousMode = noMain, previousQuantity = quantity;
    quantity = nextQuantity;
    mode(nextMode); setBusy(true);
    $('action-status').textContent = `骰子转一圈，正在揭晓 ${quantity} 样餐品…`;
    root.setTimeout(() => {
      try { const items = draw(data, noMain, randomInt, quantity); count++; show(items); }
      catch (_) { mode(previousMode); quantity = previousQuantity; $('quantity-select').value = String(quantity); $('action-status').textContent = '这次没能抽取，当前可选餐品不足或随机源不可用。请调整数量或刷新后再试。'; }
      finally { setBusy(false); loadShared(); }
    }, root.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 360);
  }
  function restore(entry, source = 'restored') {
    mode(entry.noMain);
    show(entry.ids.map(id => data.items.find(i => i.id === id)), entry.example === true ? 'example' : source, false);
  }
  function clearSharedHash() {
    if (root.location.hash.startsWith('#meal=')) {
      try { root.history.replaceState(null, '', root.location.pathname + root.location.search + '#try'); } catch (_) { /* File previews may restrict history updates. */ }
    }
  }
  async function copyText(text, message, statusId = 'copy-status') {
    const version = renderVersion;
    $('manual-copy').hidden = true;
    try { await root.navigator.clipboard.writeText(text); if (version === renderVersion) $(statusId).textContent = message; }
    catch (_) {
      if (version !== renderVersion) return;
      $('manual-copy').value = text; $('manual-copy').hidden = false;
      $('manual-copy').focus(); $('manual-copy').select();
      $(statusId).textContent = '浏览器未允许自动复制。内容已选中，请手动复制。';
    }
  }
  $('draw-button').addEventListener('click', () => { clearSharedHash(); redraw(); });
  $('hero-draw').addEventListener('click', event => { if (busy) event.preventDefault(); else { clearSharedHash(); redraw(); } });
  $('with-main').addEventListener('click', () => { clearSharedHash(); redraw(false); });
  $('without-main').addEventListener('click', () => { clearSharedHash(); redraw(true); });
  $('quantity-select').addEventListener('change', () => { clearSharedHash(); redraw(noMain, Number($('quantity-select').value)); });
  $('example-button').addEventListener('click', () => {
    clearSharedHash(); mode(false);
    show(['burger', 'fries', 'cola'].map(id => data.items.find(i => i.id === id)), 'example');
  });
  $('copy-button').addEventListener('click', () => {
    const text = `听天由麦｜${currentExample ? '固定模拟案例' : '模拟餐单'}\n${selected.map(i => `${i.name} × 1`).join('\n')}\n本轮模拟最低价：${comparison.best ? money(comparison.best.amount) : '无可比较方案'}\n${$('total-kcal').textContent}\n${data.store.name}，${data.store.address}\n全部为虚构演示，不可用于下单。\nhttps://github.com/dayebishouji/mcd-random-meal`;
    copyText(text, '模拟餐单已复制。发给朋友看看你的手气！');
  });
  $('share-button').addEventListener('click', () => {
    const url = new URL(root.location.href);
    url.search = ''; url.hash = new URLSearchParams({ meal: selected.map(i => i.id).join(','), noMain: noMain ? '1' : '0', example: currentExample ? '1' : '0' }).toString();
    copyText(url.href, '餐单链接已复制。对方打开会恢复同一份模拟餐单。', 'share-status');
  });
  $('history-list').addEventListener('click', event => {
    const button = event.target.closest('[data-history]');
    if (!button || busy) return;
    const entry = recent[Number(button.dataset.history)];
    if (entry) { clearSharedHash(); restore(entry); }
  });
  $('clear-history').addEventListener('click', () => {
    recent = []; renderHistory(); persist();
    $('action-status').textContent = '最近记录已清空，当前餐单仍保留。';
    $('draw-button').focus();
  });
  for (const [id, key] of [['budget-input', 'budget'], ['kcal-input', 'kcal']]) {
    const input = $(id), value = saved[key];
    if (typeof value === 'string' && value.length <= 10) { input.value = value; if (!input.validity.valid) input.value = ''; }
    input.addEventListener('input', () => { if (updateReference()) persist(); });
  }
  function sharedMeal() {
    const params = new URLSearchParams(root.location.hash.slice(1));
    const entry = { ids: (params.get('meal') || '').split(','), noMain: params.get('noMain') === '1', example: params.get('example') === '1' };
    if (!['0', '1'].includes(params.get('noMain')) || !validMeal(data, entry)) return null;
    if (entry.example && (entry.noMain || entry.ids.join(',') !== 'burger,fries,cola')) return null;
    return entry;
  }
  function loadShared() {
    if (!root.location.hash.startsWith('#meal=')) return false;
    const entry = sharedMeal();
    if (entry) restore(entry, 'shared');
    else $('action-status').textContent = '这个餐单链接无效或已不适用，已保留当前餐单。可以重新抽一组。';
    return !!entry;
  }
  storageNote();
  if (validMeal(data, saved.current)) restore(saved.current);
  else {
    if (saved.current && Array.isArray(saved.current.ids) && saved.current.ids.length >= 1 && saved.current.ids.length <= 6 && typeof saved.current.noMain === 'boolean') {
      quantity = saved.current.ids.length; mode(saved.current.noMain);
      $('quantity-select').value = String(quantity);
    }
    try {
      count++; show(draw(data, noMain, randomInt, quantity));
      if (saved.current) $('action-status').textContent = '旧餐单不符合当前单人餐规则，已按原数量和主食偏好重新抽取。';
    } catch (_) { $('action-status').textContent = '暂时无法准备餐单，请调整数量或刷新重试。'; setBusy(false); }
  }
  loadShared();
  root.addEventListener('hashchange', () => { if (!busy) loadShared(); });
})(typeof globalThis !== 'undefined' ? globalThis : this);
