const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const api = require(path.join(root, 'docs/app.js'));
const data = JSON.parse(fs.readFileSync(path.join(root, 'examples/demo.json'), 'utf8'));
const cases = [];
for (let a = 0; a < data.items.length; a++) for (let b = a + 1; b < data.items.length; b++) for (let c = b + 1; c < data.items.length; c++) {
  const items = [data.items[a], data.items[b], data.items[c]];
  if (items.every(i => i.kind === 'drink')) continue;
  const result = api.compare(data, items);
  cases.push({ ids: items.map(i => i.id), best: result.best.amount, baseline: result.baseline, count: result.plans.length });
}
console.log(JSON.stringify(cases));
