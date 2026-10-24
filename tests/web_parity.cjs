const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const api = require(path.join(root, 'docs/app.js'));
const data = JSON.parse(fs.readFileSync(path.join(root, 'examples/demo.json'), 'utf8'));
const cases = [];
const seen = new Set();
function record(items) {
  const key=items.map(i=>i.id).sort().join(',');
  if(seen.has(key))return;
  seen.add(key);
  const result=api.compare(data,items);
  cases.push({ids:items.map(i=>i.id),best:result.best.amount,baseline:result.baseline,count:result.plans.length});
}
const legacyIds = ['burger','chicken-burger','fish-burger','wrap','fries','nuggets','corn','wings','cola','zero','tea','pie','icecream'];
const legacyItems=data.items.filter(i=>legacyIds.includes(i.id));
function collect(start, items, quantity) {
  if (items.length === quantity) {
    if (!api.validMeal(data, {ids:items.map(i => i.id),noMain:items.every(i => i.kind !== 'main')})) return;
    record(items);
    return;
  }
  for (let i = start; i <= legacyItems.length - (quantity - items.length); i++) collect(i + 1, [...items, legacyItems[i]], quantity);
}
for (let quantity = 1; quantity <= 6; quantity++) collect(0, [], quantity);
let state=54321;
const choose=max=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state%max};
for(let quantity=1;quantity<=6;quantity++)for(const noMain of [false,true])for(let n=0;n<100;n++)record(api.draw(data,noMain,choose,quantity));
for(const noMain of [false,true])for(const quantity of [2,3])for(let n=0;n<30;n++)record(api.drawBundle(data,noMain,choose,quantity));
console.log(JSON.stringify(cases));
