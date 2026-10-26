const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto').webcrypto;
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const bare={module:{exports:{}},console,setTimeout,clearTimeout,crypto};
new vm.Script(source).runInNewContext(bare);
const {categoryOf,currentContents,pendingCandidates,readingEntries,withStyleReference,stageInputRefs,outputKinds,submitPayload,promptBody,preserveVideoMetadata}=bare.module.exports;
const plain=x=>JSON.parse(JSON.stringify(x));
const body1='【风格总控】\r\n只依据已确认风格。\r\n\r\n【场景与角色锚定】\r\n窗边人物。\r\n\r\n【分镜】\r\n镜头 1：抬头。\r\n镜头 2：移向门边。\r\n';
const video={artifact_id:'VP-G1',kind:'video_prompt',scope:'E1/S1/G1',version:1,content:body1,approval_status:'approved',metadata:{category:'video_prompt',workflow_stage:'video_prompt',title:'同次生成的两镜',episode:'第 1 集',scene:'第 1 场',generation_unit:'生成单元 1',shot:'镜头 1—2',order:[1,1,1],target_platform:'TEST 平台',target_model:'TEST 模型',extra:{preserve:true}}};
const candidate={...video,version:2,content:'【分镜】\n新的待审修改。',approval_status:'pending_review'};
const style={artifact_id:'STYLE',kind:'style_bible',scope:'project/style',version:1,content:'风格正文',approval_status:'approved'};
const stage={key:'video_prompt',label:'AI 视频提示词',category:'video_prompt',status:'mixed',counts:{approved:1,pending_candidates:1},approved_refs:[{artifact_id:video.artifact_id,version:1}],candidate_refs:[{artifact_id:video.artifact_id,version:2}],review_refs:[],dependency_suggestions:[{stage_key:'dynamic_script',label:'动态剧本',status:'available',refs:[{artifact_id:'SCRIPT',version:3}]},{stage_key:'asset',label:'资产提示词',status:'candidate',optional:true,refs:[],candidate_refs:[{artifact_id:'ASSET',version:2}]}]};
function snapshot(id='A'){
 return {project_root:'F:/TEST/'+id,project:{project_id:id,title:'TEST '+id,test_only:true},artifacts:[candidate],current_content:[video],pending_candidates:[candidate],approved_artifacts:[video,style],global_style:{status:'approved',approved_ref:{artifact_id:'STYLE',version:1},pending_refs:[{artifact_id:'STYLE',version:2}]},workflow:{mode:'screenplay',stages:[stage],optional_stages:[],definitions:{stages:[stage]}},masters:[{category:'video_prompt',version:4,segments:[video]},{category:'asset',version:9,segments:[]}],tasks:[],threads:[],media:[],events:[]};
}
function controlledForm(values){
 const error={textContent:'',focus(){}},submit={disabled:false},controls=Object.entries(values).map(([name,value])=>({name,value,disabled:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn}}));
 const form={listeners:{},elements:Object.fromEntries(controls.map(x=>[x.name,x])),addEventListener(type,fn){this.listeners[type]=fn},querySelector:q=>q==='.form-error'?error:submit,querySelectorAll:()=>[...controls,submit]};
 const FormData=class{constructor(){this.data=new Map(controls.filter(c=>!c.disabled).map(c=>[c.name,c.value]))}get(k){return this.data.get(k)??null}getAll(k){const v=this.get(k);return v===null?[]:Array.isArray(v)?v:[v]}};
 return {form,error,FormData};
}
function valuesFor(a=video){return {artifact_id:a.artifact_id,title:a.metadata.title,category:'video_prompt',scope:a.scope,chapter:'',episode:'第 1 集',scene:'第 1 场',workflow_stage:'video_prompt',target_platform:a.metadata.target_platform||'',target_model:a.metadata.target_model||'',generation_unit:'生成单元 1',shot:'镜头 1—2',content:a.content,metadata:JSON.stringify(a.metadata),deps:'[]',change_note:'TEST 修订'};}
async function ready(s=snapshot(),options={}){
 const elements=new Map(),listeners={},calls=[];let handler,document;
 function el(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,open:false,dataset:{},listeners:{},focus(){document.activeElement=this},select(){this.selected=true},scrollIntoView(){},addEventListener(t,f){this.listeners[t]=f},insertAdjacentHTML(_,h){this.innerHTML+=h},querySelector:q=>id==='editor-content'&&q==='form'?options.form?.form:null,querySelectorAll:()=>[],showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}};elements.set(id,e);return e;}
 document={getElementById:el,activeElement:null,querySelectorAll:()=>Array.from(elements.values()),addEventListener:(t,f)=>listeners[t]=f};
 const catalog={projects:[{...s.project,root:s.project_root}],bindings:[],host_context:{thread_id:'TEST-150'}};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;result={structuredContent:name==='film_board'?{...s,catalog,host_context:catalog.host_context}:options.tool?await options.tool(name,args):name==='film_snapshot'?s:catalog};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const win={scrollY:0,scrollTo(v){this.scrollY=v.top},addEventListener:(type,fn)=>{if(type==='message')handler=fn},removeEventListener(){}};
 const data=new Map(),context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},FormData:options.form?.FormData,navigator:options.navigator};
 const insertion='globalThis.__ui={accept,loadProject,navigateView,renderCards,editCandidate,readContent,readMaster,masterHistory,history,reviewCandidate,approveReader,selectReaderVersion,openReader,copyReaderPrompt,reader:()=>readerState,journal:()=>journal,epoch};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));await tick();await tick();
 return {calls,el,tick,ui:context.__ui,click:dataset=>listeners.click({target:{closest:()=>({dataset})}})};
}

test('video prompt remains separate from legacy assets and preserves one multi-shot generation unit',()=>{
 assert.equal(categoryOf(video),'video_prompt');assert.equal(categoryOf({kind:'prompt'}),'asset');assert.ok(outputKinds('seedance-prompt').includes('video_prompt'));assert.deepEqual(plain(outputKinds('video_prompt')),['video_prompt']);
 const later={...video,artifact_id:'VP-G10',scope:'E1/S1/G10',metadata:{...video.metadata,order:[1,1,10],generation_unit:'生成单元 10'}};
 const entries=readingEntries([later,video]);assert.equal(entries.length,2);assert.equal(entries[0].artifact_id,'VP-G1');assert.equal(entries[0].reader_group,'第 1 集 / 第 1 场');assert.equal(entries[0].metadata.generation_unit,'生成单元 1');assert.equal(entries[0].metadata.shot,'镜头 1—2');assert.equal(entries[0].scope,video.scope);assert.equal(entries[0].reader_text,body1);
 const cloud={...candidate,artifact_id:'CLOUD',kind:'cloud_working_draft'};const s={...snapshot(),pending_candidates:[candidate,cloud],current_content:[video,cloud]};assert.deepEqual(plain(currentContents(s).map(a=>a.artifact_id)),['VP-G1']);assert.deepEqual(plain(pendingCandidates(s).map(a=>a.artifact_id)),['VP-G1']);
});
test('video workflow routes the current-host message to seedance video mode with healthy exact style only',async()=>{
 const s=snapshot(),f=await ready(s);await f.click({workflowStage:'video_prompt'});const messages=f.calls.filter(c=>c.method==='ui/message');assert.equal(messages.length,1);const text=JSON.stringify(messages[0].params);assert.match(text,/seedance-prompt 的视频模式/);assert.match(text,/不得调用视频生成工具或模型 API/);assert.match(text,/【风格总控】【场景与角色锚定】【分镜】/);assert.match(text,/F:\/TEST\/A/);assert.match(text,/STYLE@1/);assert.match(text,/video_prompt/);assert.equal(f.calls.some(c=>c.params?.name==='film_dispatch'),false);
 assert.deepEqual(plain(stageInputRefs(stage,s)),[{artifact_id:'SCRIPT',version:3}]);assert.throws(()=>withStyleReference([{artifact_id:'STYLE',version:2}],s,'video_prompt'),/明确更新引用/);const stale={...s,global_style:{...s.global_style,status:'needs_review'}};assert.deepEqual(plain(withStyleReference([],stale,'video_prompt')),[]);assert.deepEqual(plain(stageInputRefs(stage,stale)),[{artifact_id:'SCRIPT',version:3}]);
});
test('video candidate form saves optional metadata and style refs without changing plain prompt text',async()=>{
 const a={...video,metadata:{...video.metadata,generation_unit:'生成单元 1',shot:{id:'SHOTS',title:'镜头 1—2'},extra:{preserve:true}}};
 const x=controlledForm({...valuesFor(a),target_platform:'',target_model:''});let sent;const s=snapshot(),f=await ready(s,{form:x,tool:async(name,args)=>{if(name==='film_dispatch'){sent=args.payload;return {saved:true}}return {...s,events:sent?[{data:{op_id:sent.op_id}}]:[]}}});f.ui.editCandidate(a);assert.match(f.el('editor-content').innerHTML,/一次独立生成单元（可选，可含多个镜头）/);assert.match(f.el('editor-content').innerHTML,/这里保存提示词文本，不执行视频生成/);await x.form.listeners.submit({preventDefault(){}});
 assert.equal(sent.kind,'video_prompt');assert.equal(sent.metadata.category,'video_prompt');assert.equal(sent.metadata.workflow_stage,'video_prompt');assert.equal(sent.content,body1);assert.equal(sent.scope,a.scope);assert.equal(sent.expected_project_id,'A');assert.equal(sent.metadata.target_platform,undefined);assert.equal(sent.metadata.target_model,undefined);assert.deepEqual(plain(sent.metadata.generation_unit),a.metadata.generation_unit);assert.deepEqual(plain(sent.metadata.shot),a.metadata.shot);assert.deepEqual(plain(sent.metadata.extra),{preserve:true});assert.deepEqual(plain(sent.deps),[]);assert.equal(sent.use_current_style,true);assert.equal(f.ui.journal().pending,null);
});
test('switching a new draft category exposes video fields without inventing unknown platform or model',async()=>{
 const s=snapshot(),x=controlledForm({...valuesFor(),artifact_id:'VP-NEW',target_platform:'',target_model:'',generation_unit:'',shot:'',metadata:'{}'});let sent;const f=await ready(s,{form:x,tool:async(name,args)=>{if(name==='film_dispatch'){sent=args.payload;return {saved:true}}return s}});f.ui.navigateView('artifacts','asset');f.ui.editCandidate();x.form.elements.category.value='video_prompt';x.form.elements.category.listeners.change();assert.equal(f.el('video-prompt-fields').hidden,false);await x.form.listeners.submit({preventDefault(){}});for(const key of ['target_platform','target_model','generation_unit','shot'])assert.equal(sent.metadata[key],undefined);assert.equal(sent.kind,'video_prompt');assert.equal(sent.base_version,0);
});
test('video task submission requires plain text while legacy prompt JSON remains unchanged',()=>{
 const values={artifact_id:'VP-NEW',kind:'video_prompt',base_version:'0',format:'text',content:body1,metadata:'{"extra":true}',target_platform:'',target_model:'',generation_unit:'单次生成',shot:'1—2',change_note:'TEST'},task={task_id:'T',scope:'E1/S1/G1',module:'seedance-prompt'};
 const result=submitPayload(new Map(Object.entries(values)),task,[]);assert.equal(result.content,body1);assert.equal(result.metadata.generation_unit,'单次生成');assert.equal(result.metadata.shot,'1—2');assert.equal(result.metadata.target_model,undefined);assert.equal(result.metadata.extra,true);assert.throws(()=>submitPayload(new Map(Object.entries({...values,format:'json',content:'{}'})),task,[]),/正文文本格式/);
 const legacy=submitPayload(new Map(Object.entries({...values,kind:'prompt',format:'json',content:'{"asset":"old"}'})),task,[]);assert.deepEqual(plain(legacy.content),{asset:'old'});assert.equal(preserveVideoMetadata({}, {shot:'',target_model:''}).shot,undefined);
});
test('video category and cloud working drafts render independently from asset masters',async()=>{
 const s=snapshot();s.artifacts.push({...candidate,artifact_id:'CLOUD-VIDEO',kind:'cloud_working_draft',content:'未通过的云端视频提示词'});const f=await ready(s);f.ui.navigateView('artifacts','video_prompt');assert.match(f.el('subnav').innerHTML,/data-category="video_prompt"[^>]*>AI 视频提示词/);assert.match(f.el('cards').innerHTML,/data-master="video_prompt"/);assert.doesNotMatch(f.el('cards').innerHTML,/data-master="asset"/);f.ui.navigateView('cloud','video_prompt');assert.match(f.el('cards').innerHTML,/CLOUD-VIDEO/);assert.match(f.el('cards').innerHTML,/未通过的云端视频提示词/);assert.doesNotMatch(f.el('cards').innerHTML,/通过并更新总稿/);
});
test('copy uses exact full selected history body despite search and adds no metadata or status',async()=>{
 const copied=[],s=snapshot(),f=await ready(s,{navigator:{clipboard:{writeText:async text=>copied.push(text)}},tool:async name=>name==='film_history'?{versions:[video,candidate]}:s});await f.ui.history(video.artifact_id);await f.click({readerCopyPrompt:'true'});assert.equal(copied[0],candidate.content);f.ui.selectReaderVersion(1);f.el('reader-search').value='抬头';f.el('reader-search-form').onsubmit({preventDefault(){}});await f.click({readerCopyPrompt:'true'});assert.equal(copied[1],body1);assert.match(f.el('notice').textContent,/VP-G1 · 第 1 版/);assert.equal(f.ui.journal().pending,null);assert.equal(f.calls.some(c=>c.method==='ui/message'||c.params?.name==='film_dispatch'),false);assert.throws(()=>promptBody({...video,content:{text:'not plain'}}),/准确版本正文/);
});
test('candidate comparison copy selects the candidate, then approval uses only the video master base',async()=>{
 const copied=[],s=snapshot();let sent;const f=await ready(s,{navigator:{clipboard:{writeText:async t=>copied.push(t)}},tool:async(name,args)=>{if(name==='film_dispatch'){sent=args.payload;return {approved:true}}return {...s,events:sent?[{data:{op_id:sent.op_id}}]:[]}}});f.ui.reviewCandidate(video.artifact_id);await f.click({readerCopyPrompt:'true'});assert.equal(copied[0],candidate.content);assert.match(f.el('cards').innerHTML,/当前待审候选 · 第 2 版/);assert.equal(sent,undefined);await f.ui.approveReader();assert.equal(sent.base_master_version,4);assert.equal(sent.version,2);assert.equal(sent.scope,video.scope);assert.equal(sent.synthetic,true);assert.equal(sent.expected_project_id,'A');
});
test('video master history copy follows exact segment version rather than latest artifact or master wrapper',async()=>{
 const copied=[],s=snapshot(),old={category:'video_prompt',version:1,segments:[video]},latest={category:'video_prompt',version:2,segments:[candidate]},f=await ready(s,{navigator:{clipboard:{writeText:async t=>copied.push(t)}},tool:async(name,args)=>name==='film_dispatch'&&args.action==='master.history'?{versions:[old,latest]}:s});await f.ui.masterHistory('video_prompt');f.ui.selectReaderVersion(1);await f.click({readerCopyPrompt:'true'});assert.equal(copied[0],body1);assert.equal(f.ui.reader().entries[0].version,1);assert.match(f.el('cards').innerHTML,/生成单元 1/);assert.equal(f.calls.filter(c=>c.params?.arguments?.action==='master.history').length,1);
});
test('clipboard rejection and unavailable capability offer only manually selectable exact body',async()=>{
 for(const navigator of [undefined,{clipboard:{writeText:async()=>{throw new Error('denied')}}}]){const s=snapshot(),f=await ready(s,{navigator});f.ui.openReader({mode:'content',items:[video]});await f.click({readerCopyPrompt:'true'});assert.equal(f.el('editor').open,true);assert.match(f.el('editor-content').innerHTML,/当前客户端未能自动复制/);const body=f.el('editor-content').innerHTML.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/)[1];assert.equal(body,body1);assert.equal(f.el('prompt-copy-text').selected,true);assert.equal(f.calls.some(c=>c.method==='ui/message'||c.params?.name==='film_dispatch'),false);assert.equal(f.ui.journal().pending,null);}
});
test('copy completion after selecting another version does not display a stale success notice',async()=>{
 let resolveCopy;const s=snapshot(),f=await ready(s,{navigator:{clipboard:{writeText:()=>new Promise(r=>resolveCopy=r)}},tool:async name=>name==='film_history'?{versions:[video,candidate]}:s});await f.ui.history(video.artifact_id);const copying=f.ui.copyReaderPrompt();f.ui.selectReaderVersion(1);resolveCopy();await copying;assert.doesNotMatch(f.el('notice').textContent,/已复制/);assert.equal(f.el('editor').open,false);assert.equal(f.ui.reader().entries[0].version,1);
});
test('a failed copy cannot open an old-project manual fallback after a project switch',async()=>{
 let rejectCopy;const a=snapshot(),b=snapshot('B'),f=await ready(a,{navigator:{clipboard:{writeText:()=>new Promise((_,reject)=>rejectCopy=reject)}},tool:async()=>b});f.ui.openReader({mode:'content',items:[video]});const copying=f.ui.copyReaderPrompt();await f.ui.loadProject(b.project_root);rejectCopy(new Error('late denial'));await copying;assert.equal(f.el('editor').open,false);assert.equal(f.ui.reader(),null);assert.doesNotMatch(f.el('notice').textContent,/已复制/);
});
test('copy refuses a reader whose project epoch no longer matches before touching clipboard',async()=>{
 let copies=0;const f=await ready(snapshot(),{navigator:{clipboard:{writeText:async()=>copies++}}});f.ui.openReader({mode:'content',items:[video]});f.ui.epoch.begin('F:/TEST/B');await assert.rejects(f.ui.copyReaderPrompt(),/阅读项目已变化/);assert.equal(copies,0);assert.equal(f.el('editor').open,false);
});
