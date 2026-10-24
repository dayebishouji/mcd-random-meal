const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const api = require(path.join(root, 'docs/app.js'));
const data = JSON.parse(fs.readFileSync(path.join(root, 'examples/demo.json'), 'utf8'));
const cases = [];
function collect(start, items, quantity) {
  if (items.length === quantity) {
    if (!api.validMeal(data, {ids:items.map(i => i.id),noMain:items.every(i => i.kind !== 'main')})) return;
    const result = api.compare(data, items);
    cases.push({ ids: items.map(i => i.id), best: result.best.amount, baseline: result.baseline, count: result.plans.length });
    return;
  }
  for (let i = start; i <= data.items.length - (quantity - items.length); i++) collect(i + 1, [...items, data.items[i]], quantity);
}
for (let quantity = 1; quantity <= 6; quantity++) collect(0, [], quantity);
console.log(JSON.stringify(cases));
