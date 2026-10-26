// Synthetic TEST fixtures only; no real project or installed package writes.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto:crypto,createHash}=require('node:crypto');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const bare={module:{exports:{}},console,setTimeout,clearTimeout,crypto};
new vm.Script(source).runInNewContext(bare);
const {categoryOf,currentContents,displayCategory,presentationEntry,libraryContents,videoCollections,collectionSnapshot,presentationPayload,promptBody}=bare.module.exports;
const plain=x=>JSON.parse(JSON.stringify(x));
const sha=x=>createHash('sha256').update(x).digest('hex');
function artifact(id,kind,content,metadata={},version=1){return {artifact_id:id,kind,scope:'TEST/'+id,content,version,sha256:sha(content),metadata,approval_status:'initial_draft',status:'candidate'};}
const main=artifact('DIRECTOR-MAIN','director','# 主要建议', {title:'主要导演建议'});
const full=artifact('DIRECTOR-FULL','director','# 旧导演完整稿',{title:'reading'});
const old=artifact('DIRECTOR-OLD-PICTURE','director','# 旧画面稿',{title:'旧画面提示词'});
const local=artifact('DIRECTOR-TEST','director','# 局部测试',{title:'director-plan'});
const units=Array.from({length:32},(_,i)=>artifact('VIDEO-'+String(i+1).padStart(2,'0'),'video_prompt','【风格总控】\r\n合成 TEST。\r\n【场景与角色锚定】\r\n窗边。\r\n【分镜】\r\n镜头 1：独有词'+i+'。\r\n',{title:'单元 '+(i+1),episode:{id:'EP01',title:'第01集'},scene:{id:'S'+Math.min(9,Math.floor(i/4)+1),title:'第'+Math.min(9,Math.floor(i/4)+1)+'场'},generation_unit:'U'+i,order:[1,Math.floor(i/4)+1,i]},2));
// Make 9 explicitly registered scenes, preserving 32 units.
units[31].metadata.scene={id:'S9',title:'第9场'};
function entry(a,display_category,title){return {artifact_id:a.artifact_id,version:a.version,sha256:a.sha256,display_category,title,archived:true,revision:1};}
function snapshot(id='A'){const artifacts=[main,full,old,local,...units].map(a=>plain(a));return {project_root:'TEST:/'+id,project:{project_id:id,title:'TEST '+id,test_only:true},artifacts,current_content:plain(artifacts),pending_candidates:plain(artifacts),approved_artifacts:[],masters:[],global_style:{status:'missing'},workflow:{mode:'screenplay',stages:[],optional_stages:[],definitions:{stages:[]}},tasks:[],threads:[],events:[],media:[],capabilities:{presentation_management:true},presentation:{entries:[entry(full,'director','旧完整执行包'),entry(old,'video_prompt','旧52镜画面历史参考'),entry(local,'director','第四场测试历史')]}};}
function controlledForm(values){
 const error={textContent:'',focus(){}},submit={disabled:false},controls=Object.entries(values).map(([name,value])=>({name,value,disabled:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn}}));
 const form={listeners:{},elements:Object.fromEntries(controls.map(x=>[x.name,x])),addEventListener(type,fn){this.listeners[type]=fn},querySelector:q=>q==='.form-error'?error:submit,querySelectorAll:()=>[...controls,submit]};
 const FormData=class{constructor(){this.data=new Map(controls.filter(c=>!c.disabled).map(c=>[c.name,c.value]))}get(k){return this.data.get(k)??null}getAll(k){const v=this.get(k);return v===null?[]:Array.isArray(v)?v:[v]}};
 return {form,error,FormData};
}
async function ready(s=snapshot(),options={}){
 const elements=new Map(),listeners={},calls=[];let handler,document;
 function el(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,open:false,dataset:{},listeners:{},focus(){document.activeElement=this},select(){this.selected=true},scrollIntoView(){},addEventListener(t,f){this.listeners[t]=f},insertAdjacentHTML(_,h){this.innerHTML+=h},querySelector:q=>id==='editor-content'&&q==='form'?options.form?.form:null,querySelectorAll:()=>[],showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}};elements.set(id,e);return e;}
 document={getElementById:el,activeElement:null,querySelectorAll:()=>Array.from(elements.values()),addEventListener:(t,f)=>listeners[t]=f};
 const catalog={projects:[{...s.project,root:s.project_root}],bindings:[],host_context:{thread_id:'TEST-150'}};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;result={structuredContent:name==='film_board'?{...s,catalog,host_context:catalog.host_context}:options.tool?await options.tool(name,args):name==='film_snapshot'?s:catalog};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const win={scrollY:0,scrollTo(v){this.scrollY=v.top},addEventListener:(type,fn)=>{if(type==='message')handler=fn},removeEventListener(){}};
 const data=new Map(),context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},FormData:options.form?.FormData,navigator:options.navigator};
 const insertion='globalThis.__ui={accept,loadProject,navigateView,renderCards,editCandidate,readContent,readMaster,masterHistory,history,reviewCandidate,approveReader,selectReaderVersion,openReader,copyReaderPrompt,readCollection,managePresentation,reader:()=>readerState,journal:()=>journal,epoch};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));await tick();await tick();
 return {calls,el,tick,ui:context.__ui,click:dataset=>listeners.click({target:{closest:()=>({dataset})}})};
}

test('exact presentation mapping changes only library display and never original kind, approval, scope or metadata',()=>{
 const s=snapshot(),before=JSON.stringify(s);const directors=libraryContents(s,'director');assert.deepEqual(plain(directors.map(a=>a.artifact_id)),[main.artifact_id]);assert.equal(libraryContents(s,'director',true).length,2);const historical=libraryContents(s,'video_prompt',true)[0];assert.equal(historical.artifact_id,old.artifact_id);assert.equal(categoryOf(historical),'director');assert.equal(displayCategory(historical),'video_prompt');assert.equal(historical.approval_status,'initial_draft');assert.equal(historical.scope,old.scope);assert.deepEqual(plain(historical.metadata),old.metadata);assert.equal(JSON.stringify(s),before);assert.throws(()=>promptBody(historical));
 const next={...old,version:2};assert.equal(presentationEntry(s,next),null);assert.equal(presentationEntry(s,{...old,sha256:'changed'}),null);assert.equal(presentationEntry(s,{...old,artifact_id:'other'}),null);
});
test('collections group known episode and scenes while preserving all unit refs, order, body and approval choice',()=>{
 const s=snapshot(),groups=videoCollections(libraryContents(s,'video_prompt'));assert.equal(groups.length,1);assert.equal(groups[0].title,'第01集视频提示词汇总');assert.equal(groups[0].items.length,32);assert.equal(groups[0].scenes.length,9);assert.deepEqual(plain(groups[0].items.map(a=>a.content)),units.map(a=>a.content));
 s.artifacts[4]={...s.artifacts[4],version:3,content:'尚未通过的新候选'};s.current_content[4]={...s.current_content[4],approval_status:'approved'};assert.equal(videoCollections(libraryContents(s,'video_prompt'))[0].items[0].version,2);
 const unknown=videoCollections([artifact('UNKNOWN','video_prompt','原文',{generation_unit:'第99集'})]);assert.equal(unknown[0].title,'未注明集章的提示词');assert.equal(unknown[0].key,'unstructured');
});
test('actual director and prompt lists show one current director, archived sources and one episode collection',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.navigateView('artifacts','director');let out=f.el('cards').innerHTML;assert.match(out,/主要导演建议/);assert.doesNotMatch(out,/reading|director-plan|旧画面提示词/);assert.match(out,/历史资料 · 2/);assert.match(out,/data-presentation="DIRECTOR-MAIN"/);
 await f.click({libraryMode:'history'});out=f.el('cards').innerHTML;assert.match(out,/旧完整执行包/);assert.match(out,/第四场测试历史/);assert.doesNotMatch(out,/旧52镜/);
 f.ui.navigateView('artifacts','video_prompt');out=f.el('cards').innerHTML;assert.equal((out.match(/data-collection=/g)||[]).length,1);assert.match(out,/9 场 · 32 个单元/);assert.doesNotMatch(out,/data-read="VIDEO-01"/);assert.match(out,/历史资料 · 1/);
 await f.click({libraryMode:'history'});out=f.el('cards').innerHTML;assert.match(out,/旧52镜画面历史参考/);assert.doesNotMatch(out,/data-collection=/);assert.equal(f.calls.some(c=>c.params?.name==='film_dispatch'),false);
});
test('continuous collection renders full original units, supports full-text search and exact selected-unit copy',async()=>{
 const copied=[],f=await ready(snapshot(),{navigator:{clipboard:{writeText:async x=>copied.push(x)}}});f.ui.navigateView('artifacts','video_prompt');await f.click({collection:'episode:EP01'});let out=f.el('cards').innerHTML;assert.equal((out.match(/class="reader-section collection-unit"/g)||[]).length,32);assert.match(out,/独有词31/);assert.match(out,/整集阅读按场次汇总/);assert.doesNotMatch(out,/通过并更新总稿/);
 f.el('reader-search').value='独有词31';f.el('reader-search-form').onsubmit({preventDefault(){}});out=f.el('cards').innerHTML;assert.match(out,/1 篇匹配/);assert.equal((out.match(/class="reader-section collection-unit"/g)||[]).length,1);await f.click({collectionCopy:'31'});assert.equal(copied[0],units[31].content);assert.equal(f.ui.journal().pending,null);
 await f.click({collectionOpen:'31'});assert.equal(f.ui.reader().continuous,false);assert.match(f.el('cards').innerHTML,/整集连续阅读/);await f.click({readerContinuous:'true'});assert.equal(f.ui.reader().continuous,true);
});
test('opened collection is a frozen content snapshot despite in-place fixture mutation and newer project readback',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.readCollection('episode:EP01');const frozen=f.ui.reader().entries[0].content;s.current_content[4].content='later-mutated';s.current_content[4].metadata.title='later-title';const fresh=snapshot();fresh.current_content[4].content='new-version';fresh.current_content[4].version=3;f.ui.accept(fresh);assert.equal(f.ui.reader().entries[0].content,frozen);assert.notEqual(f.ui.reader().entries[0].metadata.title,'later-title');assert.equal(f.ui.reader().entries[0].version,2);
});
test('presentation form uses precise identity, hash, revision and original WriteJournal without saving content',async()=>{
 const s=snapshot(),form=controlledForm({title:'更清楚的历史名称',display_category:'video_prompt',archived:'on'});let sent;const f=await ready(s,{form,tool:async(name,args)=>{if(name==='film_dispatch'){assert.equal(args.action,'presentation.set');sent=args.payload;return {entry:{},presentation_only:true,readback_verified:true}}return s;}});f.ui.managePresentation(full.artifact_id,1);await form.form.listeners.submit({preventDefault(){}});assert.equal(sent.artifact_id,full.artifact_id);assert.equal(sent.version,1);assert.equal(sent.expected_sha256,full.sha256);assert.equal(sent.expected_project_id,'A');assert.equal(sent.base_revision,1);assert.equal(sent.archived,true);assert.equal(sent.display_category,'video_prompt');assert.equal(sent.content,undefined);assert.equal(sent.kind,undefined);assert.ok(sent.op_id);assert.equal(f.ui.journal().pending,null);
});
test('presentation form captured for old project cannot write into a replacement project',async()=>{
 const s=snapshot(),form=controlledForm({title:'名称',display_category:'director',archived:'on'}),f=await ready(s,{form});f.ui.managePresentation(main.artifact_id,1);f.ui.accept({...snapshot('B'),project_root:s.project_root});await form.form.listeners.submit({preventDefault(){}});assert.match(form.error.textContent,/先前项目/);assert.equal(f.calls.some(c=>c.params?.arguments?.action==='presentation.set'),false);
});

test('presentation UI rejects dedicated asset/research targets and sources instead of making content disappear',()=>{
 const f=new Map(Object.entries({title:'test',display_category:'asset',archived:'on'}));assert.throws(()=>presentationPayload(f,main,null));f.set('display_category','research');assert.throws(()=>presentationPayload(f,main,null));f.set('display_category','director');assert.throws(()=>presentationPayload(f,{...main,kind:'asset'},null));assert.throws(()=>presentationPayload(f,{...main,kind:'research'},null));
});

test('list search matches computed collection title, a scene or a unit without pretending a partial subset is the full episode',async()=>{
 const f=await ready(snapshot());f.ui.navigateView('artifacts','video_prompt');for(const q of ['第01集视频提示词汇总','第9场','独有词31']){f.el('filter').listeners.input({target:{value:q}});assert.match(f.el('cards').innerHTML,/9 场 · 32 个单元/);assert.equal((f.el('cards').innerHTML.match(/data-collection=/g)||[]).length,1);}
 f.el('filter').listeners.input({target:{value:'does-not-exist'}});assert.match(f.el('cards').innerHTML,/没有找到匹配内容/);
});
test('opening and returning from historical reference preserves history list and original category-specific controls',async()=>{
 const s=snapshot(),f=await ready(s,{tool:async(name,args)=>name==='film_history'?{versions:s.artifacts.filter(a=>a.artifact_id===args.artifact_id)}:s});f.ui.navigateView('artifacts','video_prompt');await f.click({libraryMode:'history'});await f.click({read:old.artifact_id,version:'1'});assert.match(f.el('cards').innerHTML,/旧52镜画面历史参考/);assert.doesNotMatch(f.el('cards').innerHTML,/data-reader-copy-prompt/);await f.click({readerClose:'true'});assert.match(f.el('cards').innerHTML,/data-library-mode="history" aria-pressed="true"/);assert.match(f.el('cards').innerHTML,/旧52镜画面历史参考/);
});

test('merged published script labels keep source/dynamic meanings and preserve unclassified legacy script state',async()=>{
 const s=snapshot(),sourceDraft=artifact('SOURCE-SCRIPT','source_script','# 源剧本',{title:'源故事'}),legacyScript=artifact('LEGACY-SCRIPT','script','# 旧剧本',{title:'旧分场稿'});s.artifacts.push(sourceDraft,legacyScript);s.current_content.push(plain(sourceDraft),plain(legacyScript));const before=JSON.stringify(s);const f=await ready(s,{tool:async(name,args)=>name==='film_history'?{versions:s.artifacts.filter(a=>a.artifact_id===args.artifact_id)}:s});
 f.ui.navigateView('artifacts','source_script');assert.match(f.el('subnav').innerHTML,/>源剧本（底稿）</);assert.match(f.el('cards').innerHTML,/名称表示用途，不表示待审/);f.ui.navigateView('artifacts','script');assert.match(f.el('subnav').innerHTML,/>动态分场剧本</);assert.match(f.el('cards').innerHTML,/创作阶段未标注/);assert.match(f.el('cards').innerHTML,/旧稿未标注创作阶段时仍保留未知/);await f.click({read:legacyScript.artifact_id,version:'1'});assert.match(f.el('cards').innerHTML,/创作阶段未标注/);assert.match(f.el('cards').innerHTML,/分类不代表已批准或阶段完成/);assert.equal(JSON.stringify(s),before);
});
