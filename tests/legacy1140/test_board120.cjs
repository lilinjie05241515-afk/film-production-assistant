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
const {currentContents,compareContent,approvalPayload,canSwitchProject,ProjectEpoch,WriteJournal:RawWriteJournal,pendingCandidates}=bare.module.exports;
class WriteJournal extends RawWriteJournal{
 constructor(options){const read=options.read;super({...options,ownerContext:{thread_id:'TEST-UNIT-CHAT'},read:async(...args)=>{const snap=await read(...args);return snap.operations?snap:{...snap,project:snap.project||{project_id:'TEST-UNIT-PROJECT'}};}});}
 run(root,action,payload,toolName='film_dispatch'){return super.run(root,action,{...payload,...(toolName==='film_projects'?{}:{expected_project_id:payload.expected_project_id||'TEST-UNIT-PROJECT'})},toolName);}
}
const plain=x=>JSON.parse(JSON.stringify(x));
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}};
const initial={artifact_id:'SCRIPT-S01',kind:'script',scope:'C1/S1',version:1,content:'已通过原正文',metadata:{title:'第1场'}};
const candidate={...initial,version:2,content:'尚未批准的修改',approval_status:'pending_review'};
function snapshot(id){return {project_root:`F:/TEST/${id}`,project:{project_id:id,title:`TEST ${id}`,test_only:true},artifacts:[candidate],current_content:[{...initial,approval_status:'approved',pending_candidate_version:2}],pending_candidates:[candidate],masters:[],tasks:[],threads:[],media:[],events:[]};}
function fixture(onTool,options={}){
 const elements=new Map(),listeners={};
 function element(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',disabled:false,hidden:false,value:'',open:false,dataset:{},addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn},insertAdjacentHTML(_,value){this.innerHTML+=value},querySelectorAll(){return []},querySelector(selector){return options.querySelector?.(id,selector)||null},showModal(){this.open=true},close(){this.open=false;this.listeners?.close?.()},};elements.set(id,e);return e;}
 const document={getElementById:element,addEventListener:(n,f)=>listeners[n]=f};
 let messageListener;const calls=[];
 const host={postMessage(msg){calls.push(msg);if(!msg.id)return;Promise.resolve().then(async()=>{let result;try{result=msg.method==='ui/initialize'?{hostCapabilities:{}}:msg.method==='tools/call'?{structuredContent:await onTool(msg.params.name,msg.params.arguments)}:{};messageListener({source:host,data:{jsonrpc:'2.0',id:msg.id,result}});}catch(error){messageListener({source:host,data:{jsonrpc:'2.0',id:msg.id,error:{message:error.message}}});}})}};
 const win={addEventListener:(n,fn)=>{if(n==='message')messageListener=fn},removeEventListener:()=>{}};
 const context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:options.storage||storage(),FormData:options.FormData};
 const insertion='globalThis.__ui={loadProject,readProject,accept,capture,projectForm,renderCards,settingsProject,firstAssociationContext,hostContext:()=>hostContext,state:()=>state,root:()=>root,catalog:()=>catalog,epoch,journal:()=>journal};';
 const at=source.lastIndexOf('\n}');
 new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));
 return {context,calls,el:element,tick,ui:()=>context.__ui,emit:params=>messageListener({source:host,data:{jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:params}}})};
}
test('current reading uses approved content and exposes an unapproved first draft explicitly',()=>{
 const s=snapshot('A');assert.equal(currentContents(s)[0].content,'已通过原正文');assert.equal(currentContents(s)[0].pending_candidate_version,2);
 const old={artifacts:[{...candidate,approval_status:undefined}]};assert.equal(currentContents(old)[0].approval_status,'initial_draft');
 assert.equal(currentContents({artifacts:[{artifact_id:'M',kind:'render'}]}).length,0);
 const technical=['cloud_working_draft','cloud_observation','pages_observation','render'].map(kind=>({...candidate,kind,metadata:{category:'script'}}));
 assert.equal(currentContents({current_content:technical}).length,0);assert.equal(pendingCandidates({pending_candidates:technical}).length,0);
});
test('chapter, scene and shot ordering respects explicit tuple then natural scope',()=>{
 const sorted=[{scope:'C1/S10',metadata:{order:[1,10,1]}},{scope:'C1/S2',metadata:{order:[1,2,1]}},{scope:'C1/S1',metadata:{order:[1,1,2]}}].sort(compareContent);
 assert.deepEqual(sorted.map(x=>x.scope),['C1/S1','C1/S2','C1/S10']);assert.ok(compareContent({scope:'S2'},{scope:'S10'})<0);
});
test('approval freezes precise artifact scope and master base, with no invented authenticated identity',()=>{
 const p=approvalPayload(candidate,{test_only:false},{version:3});assert.equal(p.version,2);assert.equal(p.scope,'C1/S1');assert.equal(p.base_master_version,3);assert.equal(p.actor,'human');assert.equal(p.synthetic,false);
 assert.equal(p.user_authorization.real_user_id,null);assert.equal(p.user_authorization.actor_identity,'current-host-user-unresolved');assert.equal(p.user_authorization.source,'panel-click');assert.equal(p.user_authorization.artifact_id,p.artifact_id);assert.equal(p.user_authorization.version,p.version);assert.equal(p.user_authorization.scope,p.scope);
 assert.ok(Number.isFinite(Date.parse(p.user_authorization.observed_at)));
 const synthetic=approvalPayload(candidate,{test_only:true});assert.equal(synthetic.synthetic,true);assert.equal(synthetic.actor,'test-runner');assert.equal(synthetic.user_authorization,undefined);
 assert.throws(()=>approvalPayload({...candidate,version:'2'},{test_only:true}));
});
test('an editor, active write, or unresolved write blocks project switching',()=>{
 for(const flag of ['pending','busy','editorOpen'])assert.equal(canSwitchProject({[flag]:true}),false);assert.equal(canSwitchProject({}),true);
 const e=new ProjectEpoch(),a=e.begin('F:\\TEST\\A'),b=e.begin('F:/TEST/B');assert.equal(e.valid(a),false);assert.equal(e.valid(b),true);
});
test('catalog writes preserve original request and recover by read-only catalog operation receipt',async()=>{
 const saved=storage(),calls=[];let confirmed=false;
 const first=new WriteJournal({storage:saved,makeId:()=> 'CATALOG-ONE',call:async req=>{calls.push(plain(req));throw new Error('response lost')},read:async()=>({operations:[]})});
 await assert.rejects(first.run('__catalog__','register',{root:'F:/TEST/A'},'film_projects'));assert.equal(first.pending.phase,'unknown');
 const second=new WriteJournal({storage:saved,call:async()=>{throw new Error('must not resend')},read:async()=>({operations:confirmed?[{op_id:'CATALOG-ONE',result:{project:{project_id:'A'}}}]:[]})});
 await assert.rejects(second.verify(),/尚不能确认/);confirmed=true;const recovered=await second.verify();assert.equal(recovered.result.project.project_id,'A');assert.equal(calls.length,1);assert.equal(second.pending,null);
});
test('approval replay keeps synthetic flag, original master base and explicit evidence',async()=>{
 const saved=storage(),calls=[],payload=approvalPayload(candidate,{test_only:true},{version:5});
 const first=new WriteJournal({storage:saved,makeId:()=> 'APPROVAL-ONE',call:async req=>{calls.push(plain(req));throw new Error('unknown')},read:async()=>({events:[]})});
 await assert.rejects(first.run('F:/TEST/A','content.approve',payload));payload.base_master_version=9;
 const second=new WriteJournal({storage:saved,call:async req=>{calls.push(plain(req));return {approved:true}},read:async()=>({project_root:'F:/TEST/A',events:[]})});await second.retry();
 assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].payload.base_master_version,5);assert.equal(calls[1].payload.synthetic,true);
});
test('local video import journal fixes original root and operation through a lost response',async()=>{
 const saved=storage(),sent=[];const first=new WriteJournal({storage:saved,makeId:()=> 'MEDIA-ONE',call:async r=>{sent.push(plain(r));throw new Error('unknown')},read:async()=>({events:[]})});
 await assert.rejects(first.run('F:/TEST/A','import',{media_id:'M',path:'F:/SOURCE/movie.mp4',kind:'clip',metadata:{scene:'S1'}},'film_media'));
 const again=new WriteJournal({storage:saved,call:async r=>{sent.push(plain(r));return {media_id:'M'}},read:async()=>({project_root:'F:/TEST/A',events:[]})});await again.retry();assert.deepEqual(sent[0],sent[1]);assert.equal(sent[1].root,'F:/TEST/A');
});
test('actual UI initialization respects bound project, then browse switches without rewriting binding',async()=>{
 const a=snapshot('A'),b=snapshot('B'),catalog={projects:[{...a.project,root:a.project_root},{...b.project,root:b.project_root}],current_thread_project:{...a.project,root:a.project_root},resolved_project:{...a.project,root:a.project_root},host_context:{thread_id:'real-thread-A'}};
 const f=fixture(async(name,args)=>name==='film_board'?{...a,catalog,host_context:catalog.host_context}:name==='film_snapshot'?args.root.endsWith('/B')?b:a:catalog);await f.tick();await f.tick();
 assert.equal(f.ui().state().project.project_id,'A');assert.equal(f.el('project-picker').innerHTML.includes('TEST A'),true);await f.ui().loadProject(b.project_root);assert.equal(f.ui().state().project.project_id,'B');assert.match(f.el('browse-context').textContent,/正在浏览「TEST B」.*当前对话属于「TEST A」/);
 assert.equal(f.calls.some(x=>x.params?.name==='film_projects'&&x.params.arguments.action==='bind'),false);assert.deepEqual(plain(f.ui().firstAssociationContext()),{});
});
test('late project A results and notifications cannot replace a selected project B',async()=>{
 const a=snapshot('A'),b=snapshot('B'),catalog={projects:[{...a.project,root:a.project_root},{...b.project,root:b.project_root}]};let resolveA;
 const f=fixture(async(name,args)=>name==='film_board'?{...a,catalog}:name==='film_snapshot'?(args.root.endsWith('/A')?new Promise(r=>resolveA=r):b):catalog);await f.tick();await f.tick();
 const pendingA=f.ui().readProject(a.project_root);await f.tick();await f.ui().loadProject(b.project_root);resolveA(a);await pendingA;f.emit(a);await f.tick();assert.equal(f.ui().state().project.project_id,'B');assert.equal(f.ui().root(),b.project_root);
});
test('actual project switch rejects an open editor before any snapshot request',async()=>{
 const a=snapshot('A'),catalog={projects:[{...a.project,root:a.project_root}]};const f=fixture(async name=>name==='film_board'?{...a,catalog}:catalog);await f.tick();await f.tick();f.el('editor').open=true;const before=f.calls.length;await assert.rejects(f.ui().loadProject('F:/TEST/B'),/关闭编辑窗口/);assert.equal(f.calls.length,before);assert.equal(f.ui().state().project.project_id,'A');
});
test('UI keeps paths and provenance in settings/details and shows truthful local/cloud/chat actions',()=>{
 assert.match(html,/aria-label="已登记影视项目"/);assert.doesNotMatch(html,/\['review','待复核与采用'\]/);assert.match(html,/data-action="import-media-path"/);assert.match(html,/前 12 秒低清预览/);assert.match(html,/raw\._meta\.media_preview/);assert.match(html,/审核已通过，云端待同步/);assert.match(html,/cloud_working_draft/);assert.match(html,/navigate_to_codex_page/);assert.match(html,/真实创建成功后才 thread\.register/);
 const header=html.split('<header>')[1].split('</header>')[0];assert.doesNotMatch(header,/作品绝对目录|SHA-256|artifact_id|JSON/);
});
test('shared localStorage never restores chat B pending work into bound chat A',async()=>{
 const saved=storage();let writes=0;const bPending=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'CHAT-B',client_project_id:'CLIENT-SHARED'},makeId:()=> 'B-UNKNOWN',call:async()=>{writes++;throw new Error('response lost')},read:async()=>({})});
 await assert.rejects(bPending.run('F:/TEST/B','artifact.save',{artifact_id:'SCRIPT-B',expected_project_id:'B'}));const rawBefore=saved.getItem(bPending.key);assert.equal(JSON.parse(rawBefore).owner_context.thread_id,'CHAT-B');
 const a=snapshot('A'),catalog={projects:[{...a.project,root:a.project_root}],current_thread_project:{...a.project,root:a.project_root},resolved_project:{...a.project,root:a.project_root},host_context:{thread_id:'CHAT-A',client_project_id:'CLIENT-SHARED'}};
 const f=fixture(async(name,args)=>name==='film_board'?{...a,catalog,host_context:catalog.host_context}:name==='film_snapshot'?a:catalog,{storage:saved});await f.tick();await f.tick();
 assert.equal(f.ui().state().project.project_id,'A');assert.equal(f.ui().journal().pending,null);assert.match(f.ui().journal().key,/CHAT-A$/);assert.equal(saved.getItem(bPending.key),rawBefore);assert.equal(writes,1);
 assert.equal(f.calls.some(x=>x.params?.name==='film_snapshot'&&x.params.arguments.root==='F:/TEST/B'),false);
});
test('same-chat pending operation restores its original project and frozen project identity',async()=>{
 const saved=storage(),owner={thread_id:'CHAT-A'};const pending=new RawWriteJournal({storage:saved,ownerContext:owner,makeId:()=> 'SAME-CHAT',call:async()=>{throw new Error('unknown')},read:async()=>({})});await assert.rejects(pending.run('F:/TEST/B','artifact.save',{artifact_id:'B-S1',expected_project_id:'B'}));
 const a=snapshot('A'),b=snapshot('B'),catalog={projects:[{...a.project,root:a.project_root},{...b.project,root:b.project_root}],current_thread_project:{...a.project,root:a.project_root},resolved_project:{...a.project,root:a.project_root},host_context:owner};
 const f=fixture(async(name,args)=>name==='film_board'?{...a,catalog,host_context:owner}:name==='film_snapshot'&&args.root===b.project_root?b:catalog,{storage:saved});await f.tick();await f.tick();assert.equal(f.ui().state().project.project_id,'B');assert.equal(f.ui().journal().pending.phase,'unknown');assert.equal(JSON.parse(f.ui().journal().pending.requestJSON).payload.expected_project_id,'B');assert.match(f.el('browse-context').textContent,/当前对话属于「TEST A」/);
});
test('unowned legacy v1 is read-only and cannot override bound project or replay',async()=>{
 const saved=storage(),legacy={requestJSON:JSON.stringify({root:'F:/TEST/B',toolName:'film_dispatch',action:'artifact.save',payload:{op_id:'LEGACY',artifact_id:'B'}}),phase:'unknown'};saved.setItem('film-production-ui-pending-v1',JSON.stringify(legacy));
 const a=snapshot('A'),b=snapshot('B'),catalog={projects:[{...a.project,root:a.project_root}],resolved_project:{...a.project,root:a.project_root},current_thread_project:{...a.project,root:a.project_root},host_context:{thread_id:'CHAT-A'}};
 const f=fixture(async(name,args)=>name==='film_board'?{...a,catalog,host_context:catalog.host_context}:name==='film_snapshot'?b:catalog,{storage:saved});await f.tick();await f.tick();assert.equal(f.ui().state().project.project_id,'A');assert.equal(f.ui().journal().pending,null);assert.ok(f.ui().journal().legacy);await assert.rejects(f.ui().journal().retry(),/没有待核对/);await f.ui().journal().verifyLegacy();assert.equal(f.ui().state().project.project_id,'A');assert.equal(f.calls.some(x=>x.params?.name==='film_dispatch'),false);assert.equal(saved.getItem('film-production-ui-pending-v1'),JSON.stringify(legacy));
});
test('unknown thread context does not persist or recover a shared pending request',async()=>{
 const saved=storage();const a=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'A'},call:async()=>{throw new Error('unknown')},read:async()=>({})});await assert.rejects(a.run('F:/TEST/A','artifact.save',{expected_project_id:'A'}));
 const unknown=new RawWriteJournal({storage:saved,call:async()=>{throw new Error('unknown')},read:async()=>({})});assert.equal(unknown.key,null);assert.equal(unknown.pending,null);await assert.rejects(unknown.run('F:/TEST/U','artifact.save',{expected_project_id:'U'}));assert.equal(unknown.persisted,false);const reopened=new RawWriteJournal({storage:saved,call:async()=>{},read:async()=>({})});assert.equal(reopened.pending,null);assert.ok(saved.getItem(a.key));
});
test('a tampered owner record in another chat key is quarantined without replay',async()=>{
 const saved=storage(),record={owner_context:{thread_id:'B'},requestJSON:JSON.stringify({root:'F:/TEST/B',toolName:'film_dispatch',action:'artifact.save',payload:{op_id:'BAD-OWNER',expected_project_id:'B'}}),phase:'unknown'};saved.setItem('film-production-ui-pending-v2:thread:A',JSON.stringify(record));let calls=0;const a=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'A'},call:async()=>{calls++},read:async()=>({})});assert.equal(a.pending,null);assert.ok(a.legacy);await assert.rejects(a.retry());assert.equal(calls,0);
});
test('same path occupied by a different project never verifies the original write',async()=>{
 const saved=storage();const a=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'A'},makeId:()=> 'IDENTITY',call:async()=>({saved:true}),read:async()=>({project_root:'F:/TEST/A',project:{project_id:'REPLACEMENT-B'},events:[{data:{op_id:'IDENTITY'}}]})});await assert.rejects(a.run('F:/TEST/A','artifact.save',{expected_project_id:'A'}),/项目 ID/);assert.equal(a.pending.phase,'acknowledged');assert.equal(JSON.parse(a.pending.requestJSON).payload.expected_project_id,'A');
});
test('rejection on retry cannot erase an older unknown operation from the original project',async()=>{
 const saved=storage();const a=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'A'},call:async()=>{throw new Error('response lost')},read:async()=>({})});await assert.rejects(a.run('F:/TEST/A','artifact.save',{expected_project_id:'A'}));const b=new RawWriteJournal({storage:saved,ownerContext:{thread_id:'A'},call:async()=>{const error=new Error('project identity changed');error.knownRejected=true;throw error},read:async()=>({})});await assert.rejects(b.retry(),/identity changed/);assert.equal(b.pending.phase,'unknown');
});
test('unreadable registered folder retains identity and relinks from state=null without guessing the project ID',async()=>{
 const oldRoot='F:/TEST/MOVED-A',newRoot='F:/TEST/NEW-A',project={project_id:'A',title:'TEST A · moved',test_only:true,root:oldRoot,available:false};let catalog={projects:[project],current_thread_project:project,resolved_project:project,host_context:{thread_id:'CHAT-A'}},relinkPayload=null;
 const formError={textContent:''},submit={disabled:false},form={listeners:{},addEventListener(type,fn){this.listeners[type]=fn},querySelector(selector){return selector==='.form-error'?formError:submit}};
 const f=fixture(async(name,args)=>{if(name==='film_board')return {project:null,empty_state:true,catalog,host_context:catalog.host_context};if(name==='film_snapshot'){if(args.root===oldRoot)throw new Error('project registry not found');return {...snapshot('A'),project_root:newRoot};}if(name==='film_projects'&&args.action==='relink'){relinkPayload=args.payload;const moved={...project,root:newRoot,available:true};catalog={...catalog,projects:[moved],current_thread_project:moved,resolved_project:moved};return {...catalog,project:moved};}if(name==='film_projects'&&args.action==='outcome')return {found:true,operation:{op_id:relinkPayload.op_id,result:{project:catalog.resolved_project}}};return catalog;},{querySelector:(id,selector)=>id==='editor-content'&&selector==='form'?form:null,FormData:class {constructor(){return new Map([['root',newRoot],['project_id','UNTRUSTED-EDITED-FORM-ID']])}}});
 await f.tick();await f.tick();assert.equal(f.ui().state(),null);assert.equal(f.ui().settingsProject().project_id,'A');assert.match(f.el('cards').innerHTML,/重新关联源文件夹/);assert.match(f.el('project-picker').innerHTML,/value="A" selected/);
 f.ui().projectForm('relink');assert.match(f.el('editor-content').innerHTML,/name="project_id"[^>]*value="A"[^>]*readonly/);await form.listeners.submit({preventDefault(){}});await f.tick();
 assert.equal(relinkPayload.project_id,'A');assert.equal(relinkPayload.root,newRoot);assert.equal(f.ui().state().project.project_id,'A');assert.equal(f.ui().root(),newRoot);assert.equal(f.ui().journal().pending,null);assert.equal(formError.textContent,'');
});
test('closing a settings dialog restores project selection when no write remains pending',async()=>{
 const a=snapshot('A'),catalog={projects:[{...a.project,root:a.project_root}],host_context:{thread_id:'CHAT-A'}};const f=fixture(async name=>name==='film_board'?{...a,catalog,host_context:catalog.host_context}:catalog);await f.tick();await f.tick();f.ui().projectForm('manage');assert.equal(f.el('project-picker').disabled,true);f.el('editor').close();assert.equal(f.el('project-picker').disabled,false);
});
