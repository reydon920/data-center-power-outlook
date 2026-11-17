// Execute the real dashboard against a small DOM adapter; no browser or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.handlers = {}; this.textContent = ''; }
  setAttribute(k,v) { this.attrs[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  click() { this.handlers.click?.(); }
}
const ids = Object.fromEntries(['snapshot','threshold','chosen-threshold','monthly-chart','summary',
  'coverage-note','monthly-rows','download','period','sources'].map(id=>[id,new Element()]));
ids.snapshot.textContent = JSON.stringify({threshold:30,
  manifest:{start:'2025123122',sites:[{id:'test',name:'Test',latitude:0,longitude:0}],sources:[]},
  values:{test:[30,32,35,null,34,29,31]}});
const document = {
  getElementById: id=>ids[id], createElement: ()=>new Element(),
  createElementNS: ()=>new Element(), createTextNode:text=>({textContent:text})
};
let downloaded;
const context = vm.createContext({document, console, setTimeout:fn=>fn(),
  Blob, URL:{createObjectURL:blob=>{downloaded=blob;return 'blob:offline';},revokeObjectURL:()=>{}}});
vm.runInContext(fs.readFileSync('heat_exposure/web/metrics.js','utf8'), context);
vm.runInContext(fs.readFileSync('heat_exposure/web/app.js','utf8'), context);
const cells = () => ids.summary.children[0].children.map(node=>node.textContent);
assert.deepEqual(cells(), ['Test','85.71%','1','4','12','2']);
assert.equal(ids['monthly-rows'].children.length,2);
assert.match(ids['coverage-note'].textContent,/Incomplete coverage/);
assert.ok(ids['monthly-chart'].children.length > 0);
const chartBefore = JSON.stringify(ids['monthly-chart'].children);
ids.threshold.value = '34';
ids.threshold.handlers.input();
assert.deepEqual(cells(), ['Test','85.71%','1','1','1','1']);
assert.notEqual(JSON.stringify(ids['monthly-chart'].children), chartBefore);
assert.equal(ids['chosen-threshold'].textContent,'34 °C');
ids.download.click();
downloaded.text().then(csv=>{
  assert.ok(csv.includes('"whole snapshot","34","7","6","1","85.71","1","1","1"'));
  assert.ok(csv.includes('"2026-01","34"'));
  console.log('Dashboard threshold, chart, monthly table and CSV verified offline.');
}).catch(error=>{console.error(error);process.exitCode=1;});
