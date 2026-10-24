const assert=require('node:assert/strict');
const api=require('../docs/app.js');
const items=['main','side','drink','dessert'].flatMap(kind=>[0,1].map(n=>({id:kind+n,kind,selectable:true})));
const data={mode:'demo',items};
for(const noMain of [false,true]){
  const expected=new Map();
  function enumerate(start,basket){
    if(basket.length===3){
      if(!api.validMeal(data,{ids:basket.map(i=>i.id),noMain}))return;
      const key=['main','side','drink','dessert'].map(k=>basket.filter(i=>i.kind===k).length).join(',');
      expected.set(key,(expected.get(key)||0)+1);return;
    }
    for(let n=start;n<items.length;n++)enumerate(n+1,[...basket,items[n]]);
  }
  enumerate(0,[]);
  const actual=new Map(),total=Array.from(expected.values()).reduce((a,b)=>a+b,0);
  for(let ticket=0;ticket<total;ticket++){
    let first=true;
    const basket=api.draw(data,noMain,max=>{if(first){first=false;assert.equal(max,total);return ticket}return 0},3);
    const key=['main','side','drink','dessert'].map(k=>basket.filter(i=>i.kind===k).length).join(',');
    actual.set(key,(actual.get(key)||0)+1);
  }
  assert.deepEqual(actual,expected);
}
const large={mode:'demo',items:Array.from({length:300},(_,n)=>({id:String(n),kind:['main','side','drink','dessert'][n%4],selectable:true}))};
const started=Date.now();
for(let n=0;n<1000;n++){
  const basket=api.draw(large,n%2===0,()=>0,6);
  assert.equal(basket.length,6);assert.equal(new Set(basket.map(i=>i.id)).size,6);
}
assert.ok(Date.now()-started<5000,'large menu draw should not enumerate every basket');
console.log('Browser sampler: exact group weights and 1,000 six-item draws from a 300-item menu passed.');
