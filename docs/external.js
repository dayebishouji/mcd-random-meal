(function (root) {
  'use strict';
  const api = root.MealDemo || (typeof require === 'function' ? require('./app.js') : {});
  function parseMoney(value) {
    if (!/^\d{1,5}(?:\.\d{1,2})?$/.test(value)) throw new Error('金额请填写 0–10000 元，最多两位小数。');
    const [yuan, decimal = ''] = value.split('.');
    const fen = Number(yuan) * 100 + Number(decimal.padEnd(2, '0'));
    if (fen > 1000000) throw new Error('金额请填写 0–10000 元。');
    return fen;
  }
  function estimateExternal(data, selected, covered, purchase, extra) {
    if (!covered.length || new Set(covered).size !== covered.length || covered.some(id => !selected.some(i => i.id === id))) throw new Error('请按券面选择餐单内实际覆盖的餐品。');
    if (![purchase, extra].every(n => Number.isSafeInteger(n) && n >= 0 && n <= 1000000)) throw new Error('金额无效。');
    const remaining = selected.filter(i => !covered.includes(i.id));
    const comparison = remaining.length ? api.compare(data, remaining) : { best: { amount: 0, labels: [] }, truncated: false };
    if (!comparison.best) throw new Error('余餐没有可比较的模拟方案，暂不显示合计。');
    return { total: purchase + extra + comparison.best.amount, purchase, extra, remaining: comparison.best.amount,
      labels: comparison.best.labels, truncated: comparison.truncated };
  }
  Object.assign(api, { parseMoney, estimateExternal });
  if (typeof module !== 'undefined' && module.exports) module.exports = { parseMoney, estimateExternal };
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  const money = fen => `¥${(fen / 100).toFixed(2)}`;
  let current = api.current(), basketKey = '';
  function clear(message) {
    $('external-result').hidden = true;
    $('external-result').replaceChildren();
    $('external-status').textContent = message;
  }
  function mealChanged(value) {
    current = value;
    const key = value.items.map(i => i.id).sort().join(',');
    clear('餐单或模拟优惠已更新，请重新计算外部券参考价。');
    if (key === basketKey) return;
    basketKey = key;
    $('external-confirm').checked = false;
    $('external-conditions').value = '';
    $('external-items').replaceChildren();
    for (const item of value.items) {
      const label = document.createElement('label'), input = document.createElement('input'), text = document.createElement('span');
      input.type = 'checkbox'; input.value = item.id; input.name = 'covered';
      text.textContent = item.name;
      label.append(input, text); $('external-items').append(label);
    }
    clear('请选择券面实际覆盖的餐品；换一组餐单后需重新选择。');
  }
  root.addEventListener('meal:shown', event => mealChanged(event.detail));
  $('external-form').addEventListener('input', () => clear('券的信息已改变，请重新计算。'));
  $('external-form').addEventListener('submit', event => {
    event.preventDefault();
    clear('正在计算参考价…');
    if (document.querySelector('.workspace').getAttribute('aria-busy') === 'true') { clear('正在抽取新餐单，请等揭晓后再计算。'); return; }
    try {
      const covered = Array.from(document.querySelectorAll('#external-items input:checked'), input => input.value);
      const estimate = estimateExternal(current.data, current.items, covered, parseMoney($('external-price').value), parseMoney($('external-extra').value));
      const confirmed = $('external-confirm').checked;
      const total = document.createElement('strong'), detail = document.createElement('p'), conditions = document.createElement('p');
      total.textContent = `${$('external-platform').value}券参考合计 ${money(estimate.total)}`;
      detail.textContent = `购券 ${money(estimate.purchase)} ＋ 补差/费用 ${money(estimate.extra)} ＋ 模拟余餐 ${money(estimate.remaining)}${estimate.labels.length ? '（' + estimate.labels.join(' ＋ ') + '）' : '（餐单已全部覆盖）'}。${estimate.truncated ? '余餐方案已截断。' : ''}`;
      conditions.textContent = `${confirmed ? '条件由你自行核对，未向平台验证。' : '适用条件尚未核对。'}${$('external-conditions').value ? ' 备注：' + $('external-conditions').value : ''}`;
      $('external-result').append(total, detail, conditions); $('external-result').hidden = false;
      $('external-status').textContent = '已生成单张券的人工参考价；右侧模拟整单比价独立保留。';
    } catch (error) { clear(error.message); }
  });
  mealChanged(current);
})(typeof globalThis !== 'undefined' ? globalThis : this);
