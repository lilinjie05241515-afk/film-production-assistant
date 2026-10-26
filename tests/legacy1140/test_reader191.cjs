// Synthetic TEST fixtures only. This executes the real board script with a scrolling DOM double.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto,createHash}=require('node:crypto');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const pure={module:{exports:{}},console,setTimeout,clearTimeout,crypto:webcrypto};
new vm.Script(source).runInNewContext(pure);
const {compactReaderLabel,readerHeadingItems,continuousReading}=pure.module.exports;
const clone=x=>JSON.parse(JSON.stringify(x)),sha=x=>createHash('sha256').update(x).digest('hex');
function chapter(i,kind='novel',version=1){const content=`# 第${i}章\r\n\r\n## 同名小节：完整描述${i}\r\n\r\n共同词 共同词，第${i}章正文。\r\n\r\n## 结尾\r\n第${i}章END`;return {artifact_id:'TEST-CH'+i,kind,scope:'TEST/C'+i,version,content,sha256:sha(content),metadata:{title:`第${i}章_v001.md`,chapter:'第'+i+'章',order:[i]},approval_status:'approved'};}
function snapshot(items=[chapter(1),chapter(2),chapter(3)],id='TEST-191'){return {project_root:'TEST:/reader191',project:{project_id:id,title:'TEST 连续阅读',test_only:true},artifacts:clone(items),current_content:clone(items),approved_artifacts:clone(items),pending_candidates:[],masters:[],tasks:[],threads:[],events:[],media:[],capabilities:{trash_management:true},trash:{entries:[]}};}
async function ready(s=snapshot(),options={}){
 const elements=new Map(),listeners={},activeIDs=new Set(),calls=[],scrollCalls=[],copied=[],downloads=[];let handler,document,cardsWrites=0;
 const win={scrollY:0,scrollTo(v){this.scrollY=v.top;scrollCalls.push(v)},addEventListener(t,f){if(t==='message')handler=f},removeEventListener(){}};
 function el(id){if(elements.has(id))return elements.get(id);const e={id,_html:'',textContent:'',value:'',hidden:false,disabled:false,open:false,scrollTop:0,clientHeight:500,scrollHeight:3600,dataset:{},listeners:{},writes:0,
  set innerHTML(value){this._html=value;this.writes++;if(id==='cards'){cardsWrites++;for(const key of [...activeIDs])if(key.startsWith('reader-'))activeIDs.delete(key);for(const match of value.matchAll(/id="([^"]+)"/g)){activeIDs.add(match[1]);el(match[1]);}}},get innerHTML(){return this._html},
  addEventListener(t,f){this.listeners[t]=f},removeEventListener(t,f){if(this.listeners[t]===f)delete this.listeners[t]},insertAdjacentHTML(_,v){this.innerHTML+=v},
  focus(){document.activeElement=this},select(){this.selected=true},querySelector(){return null},querySelectorAll(){return []},showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()},
  scrollIntoView(){win.scrollY=420;scrollCalls.push({outer:true,id})},scrollTo({top,behavior}){this.scrollTop=top;this.lastScroll={top,behavior}},
  getBoundingClientRect(){if(id==='reader-scroll')return {top:100};const found=id.match(/^reader-(?:section|doc)-(\d+)(.*)/);if(found){const section=Number(found[1])*1000,extra=found[2].includes('reading-heading')?200:found[2].includes('reader-match')?350+Number(found[2].match(/(\d+)$/)[1])*50:0;return {top:100+section+extra-el('reader-scroll').scrollTop};}return {top:0}}
 };elements.set(id,e);return e;}
 document={activeElement:null,getElementById(id){return id.startsWith('reader-')&&!activeIDs.has(id)?null:el(id)},querySelectorAll:()=>[],addEventListener(t,f){listeners[t]=f},body:{appendChild(){}},createElement(){return {click(){downloads.push({href:this.href,download:this.download})},remove(){}}}};
 const catalog={projects:[{...s.project,root:s.project_root}],host_context:{thread_id:'TEST-191-THREAD'}};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;const answer=name==='film_board'?{...s,catalog,host_context:catalog.host_context}:options.tool?await options.tool(name,args):name==='film_snapshot'?s:catalog;result={structuredContent:answer};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const data=new Map(),context={module:{exports:{}},console,setTimeout,clearTimeout,crypto:options.crypto||webcrypto,document,parent:host,window:win,localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},navigator:{clipboard:{writeText:async t=>copied.push(t)}},TextDecoder,Uint8Array,Blob,atob,URL:{createObjectURL:()=> 'blob:TEST',revokeObjectURL(){}}};
 const injection='globalThis.__ui={openReader,readContent,readMaster,masterHistory,history,reviewCandidate,approveReader,selectReaderVersion,selectReaderItem,scrollReaderSection,renderReader,readerTOC,readerVisible,navigateView,accept,closeReader,exportReaderDocument,reader:()=>readerState};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+injection+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(r=>setImmediate(r));await tick();await tick();
 return {ui:context.__ui,el,calls,copied,downloads,scrollCalls,win,tick,cardsWrites:()=>cardsWrites,async click(dataset,sectionIndex){const button={dataset,closest:q=>q==='[data-reader-section]'&&sectionIndex!==undefined?{dataset:{readerSection:String(sectionIndex)}}:null};await listeners.click({target:{closest:()=>button}})},search(value){el('reader-search').value=value;el('reader-search-form').onsubmit({preventDefault(){}})},scroll(top){el('reader-scroll').scrollTop=top;el('reader-scroll').listeners.scroll?.()}};
}

test('directory labels shorten mechanical filenames and heading details without changing registered text',()=>{
 const a=chapter(1),before=JSON.stringify(a);assert.equal(compactReaderLabel('影视风格汇总_作者原文_v001.md'),'影视风格汇总 · 作者原文');assert.equal(compactReaderLabel('1. 画面与视觉质感：《某片》温润底色',{heading:true}),'1. 画面与视觉质感');assert.equal(compactReaderLabel('时刻 10:30',{heading:true}),'时刻 10:30');
 const heads=readerHeadingItems({...a,reader_title:a.metadata.title});assert.deepEqual(Array.from(heads,h=>h.label),['同名小节','结尾']);assert.equal(heads[0].title,'同名小节：完整描述1');assert.equal(JSON.stringify(a),before);
 assert.equal(continuousReading({mode:'master-history'}),true);assert.equal(continuousReading({mode:'review'}),false);assert.equal(continuousReading({mode:'history'}),false);assert.equal(continuousReading({mode:'collection',continuous:false}),false);
});

test('single document directory contains concise heading anchors with no fake group, repeated file or version counts',async()=>{
 const a={...chapter(1),metadata:{title:'影视风格汇总_作者原文_v001.md'},content:'# 这是我这个剧的影视风格汇总：\n\n## 1. 画面与视觉质感：长参考说明\n\n原文仍然保留。\n\n## 2. 演员表演体系：长说明\n\n细节。'},f=await ready(snapshot([a]));f.ui.openReader({mode:'content',items:[a]});const out=f.el('cards').innerHTML,toc=out.split('<nav id="reader-toc"')[1].split('</nav>')[0];assert.match(toc,/>1\. 画面与视觉质感<\/button>/);assert.match(toc,/title="1\. 画面与视觉质感：长参考说明"/);assert.doesNotMatch(toc,/未分章|影视风格汇总|字|v001|第 1 版|这是我/);assert.match(out,/影视风格汇总 · 作者原文/);assert.equal(f.ui.reader().entries[0].content,a.content);assert.match(out,/1\. 画面与视觉质感：长参考说明<\/h/);
});

test('all ordinary chapters stay mounted while chapter and heading navigation scroll only the right pane',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.openReader({mode:'content',items:s.current_content});const out=f.el('cards').innerHTML,writes=f.cardsWrites(),outer=f.win.scrollY;assert.equal((out.match(/data-reader-section=/g)||[]).length,3);for(let i=0;i<3;i++)assert.match(out,new RegExp('id="reader-doc-'+i+'-reading-heading-2"'));assert.equal(new Set([...out.matchAll(/id="([^"]+)"/g)].map(x=>x[1])).size,[...out.matchAll(/id="([^"]+)"/g)].length);
 await f.click({readerIndex:'1'});assert.equal(f.ui.reader().selected,1);assert.equal(f.el('reader-scroll').scrollTop,982);assert.equal(f.cardsWrites(),writes);assert.equal(f.win.scrollY,outer);assert.equal(f.el('cards').innerHTML,out);assert.match(f.el('reader-toc').innerHTML,/data-reader-index="1" aria-current="page"/);
 await f.click({readerAnchor:'reader-doc-1-reading-heading-2'});assert.equal(f.el('reader-scroll').scrollTop,1182);assert.equal(f.cardsWrites(),writes);assert.equal(f.win.scrollY,outer);
});

test('manual pane scroll changes the current chapter and exact copy target without replacing the body',async()=>{
 const items=[chapter(1,'video_prompt'),chapter(2,'video_prompt'),chapter(3,'video_prompt')],f=await ready(snapshot(items));f.ui.openReader({mode:'collection',items});const writes=f.cardsWrites();f.scroll(1010);assert.equal(f.ui.reader().selected,1);assert.equal(f.cardsWrites(),writes);await f.click({readerCopyPrompt:'true'});assert.equal(f.copied[0],items[1].content);assert.match(f.el('reader-current-actions').innerHTML,/TEST-CH2/);
 // Row actions bind their own exact item even if scrollspy points elsewhere.
 await f.click({collectionCopy:'2'},2);assert.equal(f.copied[1],items[2].content);assert.equal(f.ui.reader().selected,2);assert.equal(f.cardsWrites(),writes);
});

test('search has unique per-chapter anchors, follows visible chapters and hides actions when nothing matches',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.openReader({mode:'content',items:s.current_content});f.search('共同词');const out=f.el('cards').innerHTML;for(let i=0;i<3;i++)assert.match(out,new RegExp('id="reader-doc-'+i+'-reader-match-0"'));await f.click({readerNextMatch:'true',readerItem:'1'});assert.equal(f.ui.reader().selected,1);assert.equal(f.el('reader-scroll').scrollTop,1332);await f.click({readerNextMatch:'true',readerItem:'1'});assert.equal(f.el('reader-scroll').scrollTop,1382);assert.equal(f.ui.reader().entries[1].content,s.current_content[1].content);
 f.search('第3章END');assert.equal(f.ui.reader().selected,2);assert.match(f.el('cards').innerHTML,/data-reader-index="-1" disabled/);assert.doesNotMatch(f.el('cards').innerHTML,/data-reader-section="0"/);f.search('NOT_PRESENT');assert.equal(f.ui.reader().selected,-1);assert.doesNotMatch(f.el('cards').innerHTML,/data-document-export|data-reader-copy-prompt|data-trash-id/);await assert.rejects(f.ui.exportReaderDocument(),/准确正文版本/);
});

test('source mode, font changes and nested history return retain independent pane position',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.openReader({mode:'content',items:s.current_content});f.scroll(1050);const original=f.ui.reader();await f.click({readerSource:'true'});assert.equal(f.el('reader-scroll').scrollTop,1050);assert.match(f.el('cards').innerHTML,/class="markdown-source"/);await f.click({readerFont:'larger'});assert.equal(f.el('reader-scroll').scrollTop,1050);assert.equal(f.ui.reader().fontSize,18);f.ui.openReader({mode:'history',items:[s.current_content[1]],versions:[s.current_content[1]],historyVersion:1});f.scroll(150);f.ui.closeReader();assert.equal(f.ui.reader(),original);assert.equal(f.el('reader-scroll').scrollTop,1050);assert.equal(f.ui.reader().selected,1);
});

test('opened content and historical master snapshots cannot silently adopt newer refreshed bodies or other versions',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.openReader({mode:'content',items:s.current_content});s.current_content[0].content='mutated';s.current_content[0].metadata.title='mutated';f.ui.accept(snapshot([chapter(1,'novel',2),chapter(2,'novel',2)]));assert.notEqual(f.ui.reader().entries[0].content,'mutated');assert.equal(f.ui.reader().entries[0].version,1);assert.equal(f.ui.reader().entries[0].metadata.title,'第1章_v001.md');
 const old={version:1,segments:[chapter(1),chapter(2)]},latest={version:2,segments:[chapter(1,'novel',2),chapter(3,'novel',2)]};f.ui.openReader({mode:'master-history',category:'novel',items:latest.segments,versions:[old,latest],historyVersion:2,readOnly:true});f.ui.selectReaderVersion(1);assert.equal((f.el('cards').innerHTML.match(/data-reader-section=/g)||[]).length,2);assert.deepEqual(Array.from(f.ui.reader().entries,a=>a.version),[1,1]);assert.doesNotMatch(f.el('cards').innerHTML,/第3章END/);
});

test('review keeps one candidate and its exact baseline; ordinary history renders only the chosen version',async()=>{
 const base=chapter(1),candidate={...base,version:2,content:'CANDIDATE_ONLY',approval_status:'pending_review'},s=snapshot([base,chapter(2)]);s.artifacts=[candidate,chapter(2)];s.pending_candidates=[candidate];s.masters=[{category:'novel',version:6,segments:[base]}];const f=await ready(s);f.ui.reviewCandidate(base.artifact_id);let out=f.el('cards').innerHTML;assert.equal((out.match(/data-reader-section=/g)||[]).length,1);assert.match(out,/CANDIDATE_ONLY/);assert.match(out,/当前已通过 · 第 1 版/);assert.doesNotMatch(out,/第2章END/);assert.equal(f.ui.reader().baseMaster.version,6);
 f.ui.openReader({mode:'history',items:[candidate],versions:[base,candidate],historyVersion:2,latestSource:candidate});f.ui.selectReaderVersion(1);out=f.el('cards').innerHTML;assert.equal((out.match(/data-reader-section=/g)||[]).length,1);assert.doesNotMatch(out,/CANDIDATE_ONLY/);assert.equal(f.ui.reader().entries[0].version,1);assert.equal(f.calls.some(c=>c.params?.arguments?.action==='content.approve'),false);
});

test('project navigation and identity changes remove the previous pane scroll listener',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.openReader({mode:'content',items:s.current_content});const pane=f.el('reader-scroll'),oldListener=pane.listeners.scroll;assert.equal(typeof oldListener,'function');f.ui.navigateView('home');assert.equal(pane.listeners.scroll,undefined);oldListener();assert.equal(f.ui.reader(),null);f.ui.openReader({mode:'content',items:s.current_content});f.ui.accept(snapshot(s.current_content,'TEST-REPLACEMENT'));assert.equal(f.ui.reader(),null);assert.equal(pane.listeners.scroll,undefined);
});

test('export begun for one chapter is cancelled if another same-version chapter is selected during hash verification',async()=>{
 const s=snapshot(),item=s.current_content[0];let resolveDigest;const crypto={randomUUID:()=>webcrypto.randomUUID(),subtle:{digest:()=>new Promise(r=>resolveDigest=r)}};const f=await ready(s,{crypto,tool:async(name,args)=>name==='film_dispatch'&&args.action==='document.export'?{artifact_ref:{artifact_id:item.artifact_id,version:item.version},content:item.content,data_base64:Buffer.from(item.content).toString('base64'),size_bytes:Buffer.byteLength(item.content),sha256:item.sha256,filename:'TEST.md'}:s});f.ui.openReader({mode:'content',items:s.current_content});const exporting=f.ui.exportReaderDocument();await f.tick();assert.equal(typeof resolveDigest,'function');f.ui.selectReaderItem(1);resolveDigest(Buffer.from(item.sha256,'hex'));await exporting;assert.equal(f.downloads.length,0);assert.equal(f.ui.reader().selected,1);
});
