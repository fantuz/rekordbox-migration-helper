/* Exercise the actual journal controller with delayed synthetic responses. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const controller=source.slice(source.indexOf('let journalReport='),source.indexOf('function renderAnalysis(report)'));
assert(controller.includes('pollAnalyzerJournal'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
async function run(){
  let request=deferred(),capture=deferred(),posts=0,gets=0,renders=0;
  const nodes={'#analyzer-journal-watch':{checked:true},'#view-analyzer':{hidden:false},'#analyzer-journal-state':{textContent:'',dataset:{},removeAttribute:()=>{}}};
  const context=vm.createContext({$:id=>nodes[id],document:{hidden:false},busy:false,window:{addEventListener:()=>{}},I18n:{t:key=>key},Date,setInterval:()=>{},
    api:async(_url,options)=>{if(options.method){posts++;return {job:'synthetic'};}gets++;return request.promise;},
    poll:()=>capture.promise,renderAnalysis:()=>{renders++;},loadAnalyzer:async()=>{},snapshotMoment:()=>''});
  vm.runInContext(controller,context);
  const evaluate=code=>vm.runInContext(code,context);
  const select=()=>evaluate("journalCaptureSelected({id:'old',format:'Modern desktop master.db',source:'/synthetic'});journalLastRefresh=0");
  const state={supported:true,changed:true,signature:'changed'};
  select();let pending=evaluate('pollAnalyzerJournal()');
  await evaluate('pollAnalyzerJournal()');assert.equal(gets,1,'only one metadata request in flight');
  nodes['#analyzer-journal-watch'].checked=false;evaluate("$('#analyzer-journal-watch').onchange()");
  request.resolve(state);await pending;assert.equal(posts,0);assert.equal(nodes['#analyzer-journal-state'].textContent,'Journal monitoring disabled');
  nodes['#analyzer-journal-watch'].checked=true;
  select();request=deferred();pending=evaluate('pollAnalyzerJournal()');
  evaluate("journalCaptureSelected({id:'new',format:'Modern desktop master.db',source:'/new'})");
  const message=nodes['#analyzer-journal-state'].textContent;
  request.resolve(state);await pending;assert.equal(posts,0);assert.equal(nodes['#analyzer-journal-state'].textContent,message);
  // Two stable samples launch exactly one capture; a newer selection wins.
  select();request=deferred();request.resolve(state);await evaluate('pollAnalyzerJournal()');
  pending=evaluate('pollAnalyzerJournal()');await new Promise(setImmediate);assert.equal(posts,1);
  evaluate("journalCaptureSelected({id:'new',format:'Modern desktop master.db',source:'/new'})");
  capture.resolve({id:'stale',metadata_available:false});await pending;assert.equal(renders,0,'stale capture cannot replace selection');
  // A valid stable capture still renders, and failures release the polling guard.
  select();capture=deferred();await evaluate('pollAnalyzerJournal()');
  pending=evaluate('pollAnalyzerJournal()');await new Promise(setImmediate);assert.equal(posts,2);
  capture.resolve({id:'fresh',metadata_available:false});await pending;assert.equal(renders,1);
  select();request=deferred();pending=evaluate('pollAnalyzerJournal()');request.reject(new Error('synthetic failure'));await pending;
  assert.equal(evaluate('journalPolling'),false);
  console.log('Journal monitor: delayed responses, cancellation, selection changes, stable capture and errors passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
