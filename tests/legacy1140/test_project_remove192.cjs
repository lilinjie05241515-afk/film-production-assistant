// Isolated synthetic TEST catalogs and UI host; no real project or source file is touched.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto:crypto}=require('node:crypto');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const plain=x=>JSON.parse(JSON.stringify(x));
const A={project_id:'TEST-A',title:'TEST 甲项目',root:'TEST:/project-A',registered_at:'TEST-generation-A',test_only:true,available:true};
const B={project_id:'TEST-B',title:'TEST 乙项目',root:'TEST:/project-B',registered_at:'TEST-generation-B',test_only:true,available:true};
const item={artifact_id:'TEST-TEXT',kind:'novel',scope:'TEST/ch1',version:1,content:'# TEST 第一章\n\nTEST 正文。',metadata:{title:'TEST 第一章'},status:'approved',approval_status:'approved'};
function snapshot(p=A){return {project_root:p.root,project:{project_id:p.project_id,title:p.title,test_only:true},artifacts:[plain(item)],current_content:[plain(item)],approved_artifacts:[plain(item)],pending_candidates:[],masters:[],tasks:[],threads:[],events:[],media:[],capabilities:{},trash:{entries:[]}};}
async function ready(options={}){
 const elements=new Map(),listeners={},calls=[],storageData=options.storage||new Map();let handler,document;
 let projects=plain(options.projects||[A,B]),bindings=plain(options.bindings||[{kind:'thread',binding_id:'TEST-THREAD',project_id:'TEST-A'},{kind:'thread',binding_id:'TEST-OTHER',project_id:'TEST-B'}]),operations=[];
 const formError={textContent:''},submit={disabled:false},form={listeners:{},elements:{},addEventListener(t,f){this.listeners[t]=f},querySelector:q=>q==='.form-error'?formError:submit,querySelectorAll:()=>[submit]};
 function el(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',hidden:false,disabled:false,open:false,value:'',dataset:{},style:{},listeners:{},scrollTop:0,clientHeight:600,scrollHeight:600,
   focus(){document.activeElement=this},scrollIntoView(){},scrollTo(x){this.scrollTop=x.top||0},getBoundingClientRect(){return {top:0,bottom:600,height:600,left:0}},
   addEventListener(t,f){this.listeners[t]=f},removeEventListener(t,f){if(this.listeners[t]===f)delete this.listeners[t]},setAttribute(k,v){this[k]=v},insertAdjacentHTML(_,v){this.innerHTML+=v},
   querySelector:q=>id==='editor-content'&&q==='form'?form:null,querySelectorAll:()=>[],showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}};elements.set(id,e);return e;}
 document={getElementById:el,activeElement:null,querySelectorAll:()=>[...elements.values()],addEventListener:(t,f)=>listeners[t]=f};
 function listed(){const bound=bindings.find(x=>x.kind==='thread'&&x.binding_id==='TEST-THREAD');const current=projects.find(x=>x.project_id===bound?.project_id)||null;return {projects:plain(projects),bindings:plain(bindings),current_thread_project:current?plain(current):null,resolved_project:current?plain(current):null,operations:plain(operations),host_context:{thread_id:'TEST-THREAD'}};}
 function forget(args){const id=args.payload.project_id;projects=projects.filter(x=>x.project_id!==id);bindings=bindings.filter(x=>x.project_id!==id);const result={...listed(),forgotten:id,source_files_deleted:false};operations.push({op_id:args.payload.op_id,action:'forget',result:plain(result)});return result;}
 const initial=options.initial===null?null:snapshot(options.initial||A);
 async function defaultTool(name,args){
  if(name==='film_board')return {...(initial||{}),catalog:listed(),host_context:{thread_id:'TEST-THREAD'}};
  if(name==='film_snapshot'){const p=projects.find(x=>x.root===args.root);if(!p||p.available===false)throw new Error('TEST source unavailable');return snapshot(p)}
  if(name==='film_projects'){
   if(args.action==='list')return listed();
   if(args.action==='outcome'){const operation=operations.find(x=>x.op_id===args.payload.op_id);return {found:!!operation,operation:operation?plain(operation):null};}
   if(args.action==='forget')return forget(args);
   if(args.action==='register'){const p=plain(A);if(!projects.some(x=>x.project_id===p.project_id))projects.push(p);const result={...listed(),project:p};operations.push({op_id:args.payload.op_id,action:'register',result:plain(result)});return result;}
  }
  throw new Error('Unexpected synthetic tool '+name+' '+args.action);
 }
 const backend={listed,forget,defaultTool,setProjects:value=>projects=plain(value)};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;let value=options.tool?await options.tool(name,args,backend):undefined;if(value===undefined)value=await defaultTool(name,args);result=value?.__raw?value.value:{structuredContent:value};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const win={scrollY:0,scrollTo(x){this.scrollY=x.top},addEventListener:(t,f)=>{if(t==='message')handler=f},removeEventListener(){}};
 class FormData{get(k){return options.values?.[k]||null}getAll(k){return this.get(k)?[this.get(k)]:[]}}
 const context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:{getItem:k=>storageData.get(k)||null,setItem:(k,v)=>storageData.set(k,v),removeItem:k=>storageData.delete(k)},FormData};
 const insertion='globalThis.__ui={accept,projectForm,forgetProjectForm,loadProject,loadCatalog,readProject,refresh,openReader,journalResult,finishEditor,capture,view:()=>({state,root,readerState,unavailableProject,initialRoot,catalog,selectionCleared,forgotten:[...forgottenProjectIds]}),journal:()=>journal};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));await tick();await tick();
 return {calls,el,ui:context.__ui,tick,formError,submit,backend,storageData,submitForm:()=>form.listeners.submit({preventDefault(){}}),click:dataset=>listeners.click({target:{closest:()=>({dataset})}}),notify:(method,params)=>handler({source:host,data:{jsonrpc:'2.0',method,params}})};
}
const writes=f=>f.calls.filter(x=>x.method==='tools/call'&&x.params.name==='film_projects'&&!['list','outcome','resolve'].includes(x.params.arguments.action)).map(x=>x.params.arguments);
const toolCalls=(f,name)=>f.calls.filter(x=>x.method==='tools/call'&&x.params.name===name).map(x=>x.params.arguments);

test('registered project settings offer a precise one-step confirmation, cancel makes no write, empty settings offer no removal',async()=>{
 const f=await ready();f.ui.projectForm('manage');assert.match(f.el('editor-content').innerHTML,/data-action="forget-project"/);await f.click({action:'forget-project'});
 const confirmation=f.el('editor-content').innerHTML;assert.match(confirmation,/TEST 甲项目/);assert.match(confirmation,/TEST:\/project-A/);assert.match(confirmation,/对话与客户端项目关联/);assert.match(confirmation,/源文件、剧本、图片、视频、历史版本和客户端中的实际聊天都保留/);assert.match(confirmation,/关联已有/);assert.match(confirmation,/确认删除登记/);
 await f.click({action:'close'});assert.equal(f.el('editor').open,false);assert.equal(writes(f).length,0);
 const empty=await ready({initial:null,projects:[],bindings:[]});empty.ui.projectForm('manage');assert.doesNotMatch(empty.el('editor-content').innerHTML,/data-action="forget-project"/);assert.throws(()=>empty.ui.forgetProjectForm(),/先选择/);
});

test('confirmed removal sends only the frozen catalog identity and clears active reader, state and selection while preserving other project',async()=>{
 const f=await ready();f.ui.openReader({mode:'content',items:[item]});f.ui.forgetProjectForm();const before=toolCalls(f,'film_snapshot').length;await f.submitForm();assert.equal(f.formError.textContent,'');
 assert.equal(writes(f).length,1);const request=writes(f)[0];assert.equal(request.action,'forget');assert.equal(request.payload.project_id,A.project_id);assert.equal(request.payload.expected_root,A.root);assert.equal(request.payload.expected_registered_at,A.registered_at);assert.ok(request.payload.op_id);assert.equal(request.payload.root,undefined);
 const v=f.ui.view();assert.equal(v.state,null);assert.equal(v.readerState,null);assert.equal(v.root,'');assert.equal(v.initialRoot,'');assert.equal(v.unavailableProject,null);assert.equal(v.selectionCleared,true);assert.deepEqual(plain(v.catalog.projects.map(x=>x.project_id)),['TEST-B']);assert.deepEqual(plain(v.catalog.bindings.map(x=>x.project_id)),['TEST-B']);assert.equal(toolCalls(f,'film_snapshot').length,before);assert.equal(f.ui.journal().pending,null);assert.match(f.el('notice').textContent,/已删除项目登记/);assert.doesNotMatch(f.el('project-picker').innerHTML,/TEST-A/);assert.match(f.el('project-picker').innerHTML,/TEST-B/);
});

test('removing browsed B does not jump to or change the current chat bound to A',async()=>{
 const f=await ready();await f.ui.loadProject(B.root);f.ui.forgetProjectForm();const before=toolCalls(f,'film_snapshot').length;await f.submitForm();assert.equal(f.formError.textContent,'');assert.equal(writes(f)[0].payload.project_id,B.project_id);assert.equal(f.ui.view().state,null);assert.equal(f.ui.view().root,'');assert.equal(f.ui.view().catalog.current_thread_project.project_id,A.project_id);assert.deepEqual(plain(f.ui.view().catalog.projects.map(x=>x.project_id)),['TEST-A']);assert.equal(toolCalls(f,'film_snapshot').length,before);assert.doesNotMatch(f.el('project-picker').innerHTML,/ selected/);f.ui.projectForm('manage');assert.doesNotMatch(f.el('editor-content').innerHTML,/data-action="forget-project"/);f.ui.finishEditor();await f.ui.refresh();assert.equal(f.ui.view().root,'');
});

test('unavailable registered source can be removed without any source read in deletion flow',async()=>{
 const f=await ready({projects:[A,{...B,available:false}]});await assert.rejects(f.ui.loadProject(B.root),/unavailable/);f.ui.projectForm('manage');assert.match(f.el('editor-content').innerHTML,/data-action="forget-project"/);f.ui.forgetProjectForm();const before=toolCalls(f,'film_snapshot').length;await f.submitForm();assert.equal(f.formError.textContent,'');assert.equal(writes(f)[0].payload.project_id,B.project_id);assert.equal(toolCalls(f,'film_snapshot').length,before);assert.equal(f.ui.view().unavailableProject,null);
});

test('a relink or same-root re-registration after opening confirmation rejects the stale form before any write',async()=>{
 for(const changed of [{...A,root:'TEST:/moved-A'},{...A,registered_at:'TEST-new-generation'}]){const f=await ready();f.ui.forgetProjectForm();f.backend.setProjects([changed,B]);await f.ui.loadCatalog();await f.submitForm();assert.match(f.formError.textContent,/登记已变化/);assert.equal(writes(f).length,0);assert.equal(f.ui.journal().pending,null);}
});

test('late snapshot, catalog fetch, refresh and host notifications cannot resurrect a removed selection',async()=>{
 let releaseList,releaseSnapshot,holdList=false,holdSnapshot=false;const f=await ready({tool:async(name,args,backend)=>{if(holdList&&name==='film_projects'&&args.action==='list'){holdList=false;const old=backend.listed();return new Promise(resolve=>releaseList=()=>resolve(old));}if(holdSnapshot&&name==='film_snapshot'){holdSnapshot=false;return new Promise(resolve=>releaseSnapshot=()=>resolve(snapshot(A)));}}});
 const staleCatalog=f.backend.listed();holdList=true;const oldRefresh=f.ui.refresh();await f.tick();holdSnapshot=true;const oldRead=f.ui.readProject(A.root);await f.tick();f.ui.forgetProjectForm();await f.submitForm();assert.equal(f.ui.view().root,'');releaseList();releaseSnapshot();await oldRefresh;await oldRead;assert.equal(f.ui.view().state,null);assert.equal(f.ui.view().root,'');assert.doesNotMatch(f.el('project-picker').innerHTML,/TEST-A/);
 f.notify('ui/notifications/tool-result',{structuredContent:{...snapshot(A),catalog:staleCatalog}});f.notify('ui/notifications/tool-input',{arguments:{root:A.root}});await f.tick();assert.equal(f.ui.view().state,null);assert.equal(f.ui.view().initialRoot,'');assert.doesNotMatch(f.el('project-picker').innerHTML,/TEST-A/);
 f.notify('ui/notifications/tool-result',{structuredContent:{...snapshot(B),catalog:staleCatalog}});await f.tick();assert.equal(f.ui.view().root,'');assert.equal(f.ui.view().state,null);await f.ui.loadProject(B.root);f.notify('ui/notifications/tool-result',{structuredContent:{...snapshot(B),catalog:staleCatalog}});await f.tick();assert.equal(f.ui.view().state.project.project_id,B.project_id);assert.doesNotMatch(f.el('project-picker').innerHTML,/TEST-A/);
});

test('unknown completed removal recovers through outcome and list without a second write or source reload',async()=>{
 let lost=true;const f=await ready({tool:async(name,args,backend)=>{if(name==='film_projects'&&args.action==='forget'&&lost){lost=false;backend.forget(args);throw new Error('TEST reply lost after commit');}}});f.ui.forgetProjectForm();await f.submitForm();assert.match(f.formError.textContent,/reply lost/);assert.equal(f.ui.journal().pending.phase,'unknown');const op=writes(f)[0].payload.op_id;assert.equal(f.el('project-picker').disabled,true);const before=toolCalls(f,'film_snapshot').length;await f.click({pending:'retry'});assert.equal(writes(f).length,1);assert.equal(f.ui.journal().pending,null);assert.equal(f.ui.view().root,'');assert.equal(f.ui.view().state,null);assert.equal(toolCalls(f,'film_snapshot').length,before);assert.ok(toolCalls(f,'film_projects').some(x=>x.action==='outcome'&&x.payload.op_id===op));
});

test('pending removal reload stays unselected and can verify exact historical outcome while another project remains bound',async()=>{
 const storage=new Map(),op='TEST-pending-forget-B',request={toolName:'film_projects',root:B.root,action:'forget',payload:{op_id:op,project_id:B.project_id,expected_root:B.root}};storage.set('film-production-ui-pending-v2:thread:TEST-THREAD',JSON.stringify({requestJSON:JSON.stringify(request),owner_context:{thread_id:'TEST-THREAD',client_project_id:null,session_id:'old'},phase:'unknown'}));
 const f=await ready({storage,projects:[A],tool:async(name,args)=>name==='film_projects'&&args.action==='outcome'?{found:true,operation:{op_id:op,action:'forget',result:{forgotten:B.project_id,source_files_deleted:false}}}:undefined});assert.equal(f.ui.view().root,'');assert.equal(f.ui.view().state,null);assert.equal(toolCalls(f,'film_snapshot').length,0);await f.click({pending:'verify'});assert.equal(writes(f).length,0);assert.equal(f.ui.journal().pending,null);assert.equal(f.ui.view().root,'');assert.equal(f.ui.view().catalog.current_thread_project.project_id,A.project_id);
});

test('mismatched deletion outcome remains pending and never clears a different project',async()=>{
 const f=await ready({tool:async(name,args)=>name==='film_projects'&&args.action==='forget'?{forgotten:B.project_id,source_files_deleted:false}:undefined});f.ui.forgetProjectForm();await f.submitForm();assert.match(f.formError.textContent,/回读结果与原项目不符/);assert.equal(f.ui.journal().pending.phase,'acknowledged');assert.equal(f.ui.view().state.project.project_id,A.project_id);assert.equal(f.el('project-picker').disabled,true);
});

test('explicit associate-existing restores a removed project and permits reading its unchanged content',async()=>{
 const f=await ready({values:{root:A.root}});f.ui.forgetProjectForm();await f.submitForm();assert.equal(f.ui.view().root,'');f.ui.projectForm('link');await f.submitForm();assert.equal(f.formError.textContent,'');assert.equal(writes(f).length,2);assert.equal(writes(f)[1].action,'register');assert.equal(writes(f)[1].payload.root,A.root);assert.equal(f.ui.view().state.project.project_id,A.project_id);assert.equal(f.ui.view().root,A.root);assert.equal(f.ui.view().forgotten.includes(A.project_id),false);assert.equal(f.ui.view().state.current_content[0].content,item.content);
});
