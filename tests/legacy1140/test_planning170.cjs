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
const {CATEGORIES,categoryOf,currentContents,pendingCandidates,isCreative,planningStages,allWorkflowStages,planningPrompt,workflowPrompt,outputKinds,approvalPayload}=bare.module.exports;
const plain=x=>JSON.parse(JSON.stringify(x));
const candidate={artifact_id:'TEST-idea',kind:'idea',scope:'TEST/exploration',version:2,content:'两个机制方向的候选比较',metadata:{category:'idea',workflow_stage:'idea',title:'TEST 灵感候选'},approval_status:'pending_review'};
const raw={artifact_id:'TEST-raw',kind:'planning_record',scope:'TEST/exploration',version:3,content:{raw:'原话与分支'},metadata:{category:'idea'}};
function snapshot(id='A',mode='unset'){
 const stages=[{key:'idea',category:'idea',label:'灵感探索',status:'candidate',counts:{approved:0,pending_candidates:1},candidate_refs:[{artifact_id:'TEST-idea',version:2}],dependency_suggestions:[]},{key:'requirements',category:'requirements',label:'需求与执行规划',status:'empty',counts:{approved:0,pending_candidates:0},dependency_suggestions:[]}];
 return {project_root:'TEST:/'+id,project:{project_id:id,title:'TEST '+id,test_only:true},artifacts:[candidate,raw],current_content:[candidate,raw],pending_candidates:[candidate,raw],approved_artifacts:[],masters:[],global_style:{status:'missing'},workflow:{mode,stages:[],optional_stages:[],preproduction_stages:stages,definitions:{stages}},planning_records:[{record_id:'TEST-record',record_kind:'idea',title:'TEST 原话记录',scope:'TEST/exploration',version:3,status:'parked',next_step:'下一步未安排'}],tasks:[{task_id:'TEST-task',title:'TEST 需求任务',module:'requirements-planner',scope:'TEST/requirements',status:'created'}],threads:[],media:[],events:[]};
}
async function ready(s=snapshot(),options={}){
 const elements=new Map(),listeners={},calls=[];let handler,document;
 function el(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,open:false,dataset:{},listeners:{},focus(){document.activeElement=this},scrollIntoView(){},addEventListener(t,f){this.listeners[t]=f},insertAdjacentHTML(_,h){this.innerHTML+=h},querySelector:()=>null,querySelectorAll:()=>[],showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}};elements.set(id,e);return e;}
 document={getElementById:el,activeElement:null,querySelectorAll:()=>Array.from(elements.values()),addEventListener:(t,f)=>listeners[t]=f};
 const catalog={projects:s?.project?[{...s.project,root:s.project_root}]:[],bindings:[],host_context:{thread_id:'TEST-170'}};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;result={structuredContent:name==='film_board'?{...(s||{}),catalog,host_context:catalog.host_context}:options.tool?await options.tool(name,args):name==='film_snapshot'?s:catalog};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const win={scrollY:0,scrollTo(v){this.scrollY=v.top},addEventListener:(type,fn)=>{if(type==='message')handler=fn},removeEventListener(){}};
 const data=new Map(),context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}};
 const insertion='globalThis.__ui={accept,loadProject,navigateView,renderCards,editCandidate,history,reviewCandidate,readPlanningRecord,reader:()=>readerState,journal:()=>journal,epoch};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));await tick();await tick();
 return {calls,el,tick,ui:context.__ui,click:dataset=>listeners.click({target:{closest:()=>({dataset})}})};
}
const requestText=f=>f.calls.filter(c=>c.method==='ui/message').map(c=>c.params.content[0].text);
const writes=f=>f.calls.filter(c=>c.method==='tools/call'&&c.params.name==='film_dispatch'&&c.params.arguments.action!=='planning.read'&&c.params.arguments.action!=='master.history');

test('planning candidate identities are separate and raw records cannot enter creative approval',()=>{
 assert.equal(CATEGORIES.idea,'灵感探索');assert.equal(CATEGORIES.requirements,'需求与执行规划');
 assert.equal(categoryOf({kind:'requirements'}),'requirements');assert.equal(categoryOf({kind:'prompt'}),'asset');
 assert.equal(isCreative(raw),false);assert.deepEqual(plain(currentContents(snapshot()).map(a=>a.artifact_id)),['TEST-idea']);assert.deepEqual(plain(pendingCandidates(snapshot()).map(a=>a.artifact_id)),['TEST-idea']);
 assert.deepEqual(plain(outputKinds('idea-explorer')),['idea']);assert.deepEqual(plain(outputKinds('requirements-planner')),['requirements']);assert.throws(()=>approvalPayload(raw,snapshot().project,null),/不可通用批准/);
});
test('both optional stages remain available before route selection and do not invent counts',()=>{
 for(const mode of ['unset','novel_only','novel_to_screen','screenplay']){const s=snapshot('A',mode),before=JSON.stringify(s),stages=planningStages(s);assert.deepEqual(plain(stages.map(x=>x.key)),['idea','requirements']);assert.ok(stages.every(x=>x.optional));assert.equal(JSON.stringify(s),before);assert.equal(allWorkflowStages(s).length,2);}
 const fresh=planningStages(null);assert.equal(fresh[0].counts,undefined);assert.equal(fresh[1].module,'requirements-planner');
});
test('unbound panel starts current-chat exploration without initializing a project or writing data',async()=>{
 const f=await ready(null);assert.match(f.el('cards').innerHTML,/先聊灵感或需求/);await f.click({tab:'planning'});assert.match(f.el('cards').innerHTML,/data-workflow-stage="idea"/);assert.match(f.el('cards').innerHTML,/data-workflow-stage="requirements"/);assert.doesNotMatch(f.el('cards').innerHTML,/data-open-category/);
 await f.click({workflowStage:'idea'});const messages=requestText(f);assert.equal(messages.length,1);assert.match(messages[0],/film_modules\(module="idea"\)/);assert.match(messages[0],/idea-explorer/);assert.match(messages[0],/尚未绑定或选择影视项目/);assert.match(messages[0],/不要调用 project.init \/ film_projects create/);assert.match(messages[0],/仅登记.*暂时搁置/s);assert.equal(writes(f).length,0);assert.equal(f.calls.some(c=>c.params?.name==='film_projects'&&['create','register'].includes(c.params.arguments.action)),false);
});
test('unset project workflow and planning tab expose independent cards and exact project context',async()=>{
 const f=await ready();f.ui.navigateView('workflow');assert.match(f.el('cards').innerHTML,/data-workflow-stage="idea"/);assert.match(f.el('cards').innerHTML,/data-workflow-stage="requirements"/);f.ui.navigateView('planning');assert.match(f.el('tabs').innerHTML,/灵感与需求/);assert.match(f.el('cards').innerHTML,/TEST 原话记录/);assert.match(f.el('cards').innerHTML,/下一步未安排/);
 await f.click({workflowStage:'requirements'});const [message]=requestText(f);assert.match(message,/项目 ID：A/);assert.match(message,/路线：unset/);assert.match(message,/requirements-planner/);assert.match(message,/信息已明确且已有可追溯执行授权时直接推进/);assert.match(message,/不强制先脑暴再规划/);assert.match(message,/planning.record/);assert.match(message,/不得在项目内运行模块 records.py/);assert.equal(writes(f).length,0);
});
test('planning record opens exact snapshot version through the dedicated read-only action',async()=>{
 let received;const f=await ready(snapshot(),{tool:async(name,args)=>{received={name,args};return {record:{record_id:'TEST-record',entries:[{text:'TEST 原话'}]},artifact_ref:{artifact_id:'TEST-raw',version:3},changes:[]}}});f.ui.navigateView('planning');await f.click({planningRead:'TEST-record'});
 assert.equal(received.name,'film_dispatch');assert.equal(received.args.action,'planning.read');assert.deepEqual(plain(received.args.payload),{expected_project_id:'A',record_id:'TEST-record',version:3,limit:40});assert.equal(received.args.root,'TEST:/A');assert.match(f.el('editor-content').innerHTML,/TEST 原话/);assert.match(f.el('editor-content').innerHTML,/不可通过普通内容编辑或批准/);assert.doesNotMatch(f.el('editor-content').innerHTML,/<form|data-reader-approve/);assert.equal(writes(f).length,0);
});
test('planning read cannot display a stale result after project switch',async()=>{
 let release;const blocked=new Promise(resolve=>release=resolve),f=await ready(snapshot(),{tool:async(name,args)=>name==='film_dispatch'?blocked:name==='film_snapshot'?snapshot('B'):{projects:[],bindings:[]}});
 const reading=f.ui.readPlanningRecord('TEST-record');await f.tick();await f.ui.loadProject('TEST:/B');release({record:{title:'wrong old project result'}});await assert.rejects(reading,/项目已切换/);assert.doesNotMatch(f.el('editor-content').innerHTML,/wrong old project/);
});
test('late planning read cannot reopen a dialog after navigation to another module',async()=>{
 let release;const delayed=new Promise(resolve=>release=resolve),f=await ready(snapshot(),{tool:async()=>delayed});
 const reading=f.ui.readPlanningRecord('TEST-record');await f.tick();f.ui.navigateView('artifacts','idea');release({record:{title:'late obsolete record'}});await reading;assert.equal(f.el('editor').open,false);assert.doesNotMatch(f.el('editor-content').innerHTML,/late obsolete record/);
});
test('raw planning history offers no edit or restore and cannot open a generic edit form',async()=>{
 const f=await ready(snapshot(),{tool:async name=>name==='film_history'?{versions:[raw]}:snapshot()});assert.throws(()=>f.ui.editCandidate(raw),/不能在此直接改写/);await f.ui.history(raw.artifact_id);assert.equal(f.ui.reader().readOnly,true);assert.doesNotMatch(f.el('cards').innerHTML,/data-reader-edit|data-reader-restore|data-reader-approve/);assert.throws(()=>f.ui.reviewCandidate(raw.artifact_id),/没有该条目的待审核版本/);
});
test('candidate categories and actual specialist task names remain readable',async()=>{
 const f=await ready();f.ui.navigateView('artifacts','idea');assert.match(f.el('subnav').innerHTML,/data-category="requirements"/);assert.match(f.el('cards').innerHTML,/TEST 灵感候选/);assert.doesNotMatch(f.el('cards').innerHTML,/TEST-raw/);f.ui.navigateView('tasks');assert.match(f.el('cards').innerHTML,/需求与执行规划/);assert.doesNotMatch(f.el('cards').innerHTML,/>requirements-planner</);
});
test('host exploration is distinct from the unchanged unconnected external brainstorm interface',async()=>{
 const f=await ready();f.ui.navigateView('brainstorm');assert.match(f.el('cards').innerHTML,/外部生成提供方的只读接口/);assert.match(f.el('cards').innerHTML,/idea-explorer/);assert.match(f.el('cards').innerHTML,/data-tab="planning"/);assert.equal(writes(f).length,0);
 const prompt=workflowPrompt(planningStages(snapshot())[0],snapshot(),'TEST:/A');assert.match(prompt,/provider_status=not_connected、can_generate=false/);assert.match(prompt,/完整 SKILL.md/);assert.match(prompt,/不从喜好、候选通过或时间经过推定授权/);
});
