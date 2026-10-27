// All fixtures are test_only synthetic. This suite drives the actual 1.15.0
// management handlers in a VM host; it is not a native-client visual acceptance.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto:crypto,createHash}=require('node:crypto');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const pure={module:{exports:{}},console,crypto,setTimeout,clearTimeout};
new vm.Script(source).runInNewContext(pure);const h=pure.module.exports;new vm.Script("module.exports.taskGroup2000=taskGroup2000;module.exports.overviewCover2000=overviewCover2000;").runInNewContext(pure);
const plain=value=>JSON.parse(JSON.stringify(value));
const sha=value=>createHash('sha256').update(value).digest('hex');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const body='# Synthetic 第一场\r\n\r\n**完整正文**：他把灯放在窗前。\r\n\r\n- 进入\r\n  - 回望\r\n\r\n| 位置 | 动作 |\r\n| --- | --- |\r\n| 窗前 | 放灯 |\r\n\r\n```text\r\n<原文保留>\r\n```\r\n\r\n结尾-END\r\n';
const oldBody=body.replace('窗前','门边');
function item(overrides={}){return {target_type:'artifact',target_id:'SCRIPT',version:2,sha256:sha(body),kind:'script',media_kind:'document',scope:'episode/1',title:'合成剧本',category_id:'script',tags:['夜景'],asset_id:null,revision:0,deleted:false,trash_revision:0,version_roles:['latest_working'],latest_working_version:2,latest_adopted_version:1,locked_by:[],production_locked_by:[],adoption:{status:'not_recorded',records:[]},review_status:'not_recorded',...overrides};}
function snap(id='TEST-A'){
 const a=item(),v1=item({version:1,sha256:sha(oldBody),version_roles:['latest_adopted','task_input_locked'],adoption:{status:'current_adopted',records:[]},locked_by:[{task_id:'T-OLD',scope:'episode/1',status:'cancelled'}]});
 const image=item({target_type:'media',target_id:'IMAGE',version:undefined,sha256:sha('image'),kind:'image',media_kind:'image',scope:null,title:'合成参考图',category_id:'character',version_roles:[],path:'assets/synthetic.png'});
 const audio={...image,target_id:'AUDIO',kind:'audio',media_kind:'audio',title:'合成音频',sha256:sha('audio'),category_id:'music'};
 const prompt=item({target_id:'PROMPT',kind:'prompt',version:1,title:'人物参考图提示词',sha256:sha('纯文字提示词'),category_id:'asset',version_roles:['latest_working']});
 const art=(x,content)=>({artifact_id:x.target_id,version:x.version,sha256:x.sha256,kind:x.kind,scope:x.scope,metadata:{title:x.title},content});
 return {project_root:'C:/TEST_ONLY/'+id,project:{project_id:id,title:'Synthetic '+id,test_only:true},artifacts:[art(a,body),art(prompt,'纯文字提示词')],approved_artifacts:[art(v1,oldBody)],current_content:[],media:[],threads:[{thread_id:'TEST-CHAT',title:'合成导演工作对话',scope:'episode/1'}],tasks:[],sync:[],events:[],observed_at:'2026-10-26T05:00:00Z',cloud:{documents:[]},board_library:{items:[a,v1,prompt,image,audio],categories:{document:{revision:0,categories:[{id:'script',label:'剧本'},{id:'asset',label:'资产提示词'}]},image:{revision:0,categories:[{id:'character',label:'人物'},{id:'scene',label:'场景'}]},video:{revision:0,categories:[{id:'take',label:'生成素材'}]},audio:{revision:0,categories:[{id:'music',label:'音乐'},{id:'other',label:'其他'}]}},overview:{global_baseline:[],representative_chapters:[],current_batches:[],declared_scope:[],episodes:[{id:'1',title:'第1集',items:[a,v1],completion_status:'unknown'}],next_steps:[],completion_percent:null,scope_status:'not_recorded'},reviews:{entries:[{record_type:'adoption',record_id:'D1',artifact_ref:{artifact_id:'SCRIPT',version:1,sha256:sha(oldBody)},scope:'episode/1',status:'adopt',source:{type:'synthetic'},observed_at:'2026-10-26T04:00:00Z',details:{evidence:'synthetic confirmation'},latest_version:2,applies_to_latest:false}]}}};
}
function store(){const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key),values};}
function decode(s){return String(s).replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');}
async function uiFixture({snapshot=snap(),handler=null,storage=store()}={}){
 const elements=new Map(),listeners={},calls=[],copied=[],opened=[];let messageHandler,currentSnapshot=snapshot;
 const catalog=()=>({projects:[{...currentSnapshot.project,root:currentSnapshot.project_root,available:true}],bindings:[],host_context:{thread_id:'TEST-OWNER'},current_thread_project:null});
 function makeForm(html){const values={};for(const m of html.matchAll(/<input\b([^>]+)>/g)){const name=m[1].match(/name="([^"]+)"/),v=m[1].match(/value="([^"]*)"/);if(name)values[name[1]]=decode(v?.[1]||'');}for(const m of html.matchAll(/<select\b[^>]*name="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const opts=[...m[2].matchAll(/<option value="([^"]*)"([^>]*)>/g)],value=opts.find(x=>x[2].includes('selected'))||opts[0];values[m[1]]=decode(value?.[1]||'');}const error={textContent:''},submit={disabled:false},handlers={};return {values,error,submit,handlers,addEventListener:(type,fn)=>handlers[type]=fn,querySelector:q=>q==='.form-error'?error:submit};}
 function el(id){if(elements.has(id))return elements.get(id);let inner='';const handlers={};const e={id,textContent:'',value:'',disabled:false,open:false,dataset:{},checked:false,handlers,focus(){},select(){},scrollIntoView(){this.scrolled=true},setSelectionRange(){},addEventListener:(type,fn)=>handlers[type]=fn,showModal(){this.open=true},close(){this.open=false;handlers.close?.()},querySelector(q){if(id==='dialog-body'&&q==='form')return this.form;if(id==='dialog-body'&&q==='textarea')return el('reference-copy');if(q==='.prose')return el(id+'-prose');if(q==='[data-action=add-category]')return el('add-category');return el(id+'-'+q);},get lastElementChild(){return {querySelector:()=>({focus(){}})};},get innerHTML(){return inner},set innerHTML(value){inner=String(value);if(id==='dialog-body'&&/<form\b/.test(inner))this.form=makeForm(inner);for(const m of inner.matchAll(/<textarea id="([^"]+)"[^>]*>([\s\S]*?)<\/textarea>/g))el(m[1]).value=decode(m[2]);}};elements.set(id,e);return e;}
 const document={getElementById:el,addEventListener:(type,fn)=>listeners[type]=fn};
 const host={postMessage(message){calls.push(plain(message));if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='ui/initialize')result={hostContext:{thread_id:'TEST-OWNER'}};else if(message.method==='ui/open-link'){opened.push(message.params.url);result={opened:true};}else if(message.method==='tools/call'){const args=message.params.arguments;let data;if(handler)data=await handler(args,{get:()=>currentSnapshot,set:s=>currentSnapshot=s});if(data===undefined){if(args.action==='snapshot')data={...currentSnapshot,catalog:catalog(),host_context:{thread_id:'TEST-OWNER'}};else if(args.action==='projects.list')data=catalog();else if(args.action==='artifact.history')data={versions:[...currentSnapshot.approved_artifacts,...currentSnapshot.artifacts].filter(x=>x.artifact_id===args.payload.artifact_id).sort((a,b)=>a.version-b.version)};else if(args.action==='artifact.get')data=[...currentSnapshot.approved_artifacts,...currentSnapshot.artifacts].find(x=>x.artifact_id===args.payload.artifact_id&&x.version===args.payload.version);else if(h.MANAGE_ACTIONS.has(args.action)){currentSnapshot.events.push({data:{op_id:args.payload.op_id,result:{saved:true}}});data={saved:true};}else data={};}result=data?.structuredContent?data:{structuredContent:data};}messageHandler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){messageHandler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}});}};
 const window={addEventListener:(type,fn)=>{if(type==='message')messageHandler=fn;},removeEventListener(){},confirm:()=>true};
 class TestFormData{constructor(form){this.values=form.values;}get(key){return this.values[key]??null;}*[Symbol.iterator](){yield*Object.entries(this.values);}}
 const context={module:{exports:{}},console,crypto,setTimeout,clearTimeout,parent:host,window,document,localStorage:storage,FormData:TestFormData,navigator:{clipboard:{writeText:async text=>copied.push(text)}}};
 const expose='globalThis.__ui={setTheme2000,backDialog2000,show,actionHandler,navigate,accept,refresh,switchProject,readArtifact,fillDocumentBodies,showHistory,compareHistory,manage,manageCategories,organize,batchOrganize,trashItems,exportSelection,importMedia,preview,original,openReference,openExactArtifact,call,render,selected:()=>selected,state:()=>state,journal:()=>journal,root:()=>root,view:()=>view,capture,isCurrent,closeDialog};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+expose+source.slice(at)).runInNewContext(context);
 await tick();await tick();await tick();
 const click=async dataset=>{await context.__ui.actionHandler({dataset,disabled:false});await tick();};
 const eventClick=async dataset=>{const button={dataset,disabled:false};listeners.click({target:{closest:()=>button}});await tick();await tick();};
 const submit=async values=>{const form=el('dialog-body').form;Object.assign(form.values,values);await form.handlers.submit({preventDefault(){}});await tick();return form;};
 return {ui:context.__ui,el,calls,copied,opened,click,eventClick,submit,listeners,elements,setSnapshot:s=>currentSnapshot=s,snapshot:()=>currentSnapshot,tick};
}

function creatorSnap(){const s=snap();s.project.profile_revision=0;s.creator_board={confirm_targets:[{artifact_id:'SCRIPT',version:2,sha256:sha(body),base_master_version:1}],objects:[{object_id:'elder',title:'老人',type:'character',intro:'测试角色',scope:'project',revision:1}],links:[{target_type:'media',target_id:'IMAGE',object_id:'elder',purpose:'日常造型',reference_only:false,sha256:sha('image'),revision:1}],selections:[],decisions:[]};return s;}

test('2.0 task statuses keep cancellation and unknown states outside completed or active',()=>{
 const s=creatorSnap();s.tasks=['cancelled','blocked','future_state','completed','created','in_progress'].map((status,i)=>({task_id:'T'+i,title:status,module:'screenplay',status}));
 assert.deepEqual(plain(h.creatorTaskRows(s).map(t=>t.group)),['cancelled','attention','attention','done','planned','active']);
 for(const layout of ['list','board']){const rendered=h.renderTasks(s,{stage:'writer',layout});for(const t of s.tasks)assert.ok(rendered.includes(t.title));assert.match(rendered,/已取消/);assert.match(rendered,/状态待核对/);}
});
test('2.0 overview chooses only exact current cover or selected image',()=>{
 const s=creatorSnap();const i=s.board_library.items.find(x=>x.target_type==='media'&&x.media_kind==='image');
 assert.equal(h.overviewCover2000(s).item,null);s.project.cover={media_id:i.target_id,sha256:'wrong'};assert.equal(h.overviewCover2000(s).item,null);
 s.project.cover.sha256=i.sha256;assert.equal(h.overviewCover2000(s).item.target_id,i.target_id);s.project.cover=null;
 s.creator_board.selections=[{purpose:'造型',reference:{target_id:i.target_id,sha256:'wrong'}}];assert.equal(h.overviewCover2000(s).item,null);
 s.creator_board.selections[0].reference.sha256=i.sha256;assert.equal(h.overviewCover2000(s).item.target_id,i.target_id);
});
test('2.0 changing theme retains the current view and draft without backend writes',async()=>{
 const storage=store(),f=await uiFixture({storage});await f.click({view:'tasks'});const markup=f.el('content').innerHTML;f.el('pv-quote').value='未提交的反馈';const count=f.calls.length;
 f.ui.setTheme2000('light');assert.equal(storage.getItem('film-board-appearance-v2'),'light');assert.equal(f.el('content').innerHTML,markup);assert.equal(f.el('pv-quote').value,'未提交的反馈');assert.equal(f.calls.length,count);
 f.ui.setTheme2000('dark');assert.equal(storage.getItem('film-board-appearance-v2'),'dark');
});
test('2.0 backing out of confirmation restores exact reader and scroll without a write',async()=>{
 const f=await uiFixture({snapshot:creatorSnap()});await f.click({openKey:h.itemKey(f.snapshot().board_library.items[0])});const original=f.el('dialog-body').innerHTML;f.el('dialog-body').scrollTop=180;
 await f.click({confirmArtifact:h.itemKey(f.snapshot().board_library.items[0])});assert.match(f.el('dialog-body').innerHTML,/确认采用/);
 f.ui.backDialog2000();assert.equal(f.el('dialog-body').innerHTML,original);assert.equal(f.el('dialog-body').scrollTop,180);assert.equal(f.el('dialog').open,true);assert.equal(f.calls.filter(x=>h.MANAGE_ACTIONS.has(x.params?.arguments?.action)).length,0);
});
test('2.0 list and board both preserve current next step and hide cancelled stale next step',()=>{
 const s=creatorSnap();s.tasks=[{title:'当前任务',module:'screenplay',status:'in_progress',checkpoints:[{completed:['开场完成'],unresolved:['人物动机'],next_step:'补充选择'}]},{title:'旧任务',module:'screenplay',status:'cancelled',checkpoints:[{next_step:'过时指令'}]}];
 for(const layout of ['list','board']){const out=h.renderTasks(s,{stage:'writer',layout});assert.match(out,/补充选择/);assert.match(out,/人物动机/);assert.doesNotMatch(out,/过时指令/);}
});

test('2.0 refreshed video panel never restores disposed playback nodes',async()=>{const f=await uiFixture();f.ui.show('预演','<video id="pv-camera"></video>');f.ui.show('预演新状态','<video id="pv-camera"></video>');assert.equal(f.el('dialog-back').hidden,true);});
