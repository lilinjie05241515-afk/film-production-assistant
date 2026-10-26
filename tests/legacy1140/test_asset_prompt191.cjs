// All content, media and projects here are isolated synthetic TEST fixtures.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto:crypto}=require('node:crypto');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const plain=x=>JSON.parse(JSON.stringify(x));
const BODY='# 制作人物资产的提示词\n\n**TEST 人物**：深灰外套，铜扣。\n\n```text\nexact prompt: [A] + B\n```\n';
const approved={artifact_id:'TEST-PROMPT',version:1,kind:'prompt',scope:'TEST/character',sha256:'a'.repeat(64),content:BODY,metadata:{title:'TEST 人物制作提示词',category:'asset',asset_type:'character'},approval_status:'approved',status:'approved',deps:[]};
const candidate={...approved,version:2,sha256:'b'.repeat(64),content:BODY+'\nTEST 候选改动。\n',metadata:{...approved.metadata,title:'TEST 人物制作提示词待审'},approval_status:'pending_review',status:'candidate'};
const legacy={artifact_id:'TEST-LEGACY-ASSET',version:1,kind:'asset',scope:'TEST/legacy',sha256:'c'.repeat(64),content:'TEST 历史资产文本：需要保持原业务kind。',metadata:{title:'TEST 历史资产文字',asset_type:'scene'},approval_status:'initial_draft',status:'candidate',deps:[]};
const image={media_id:'TEST-IMAGE-ONLY',kind:'image',path:'03-assets/TEST.png',sha256:'d'.repeat(64),metadata:{title:'TEST 图片原件不可混入提示词',asset_type:'character',category:'asset'},classification_revision:0,status:'registered'};
function snapshot(){return {project_root:'TEST:/ASSET-191',project:{project_id:'TEST-ASSET-191',title:'TEST only',test_only:true},artifacts:plain([candidate,legacy]),current_content:plain([approved,legacy]),pending_candidates:plain([candidate,legacy]),approved_artifacts:plain([approved]),masters:[],media:plain([image]),tasks:[],threads:[],events:[],trash:{entries:[]},board_order:{groups:{}},capabilities:{presentation_management:true,trash_management:true,board_ordering:true},global_style:{status:'missing'},workflow:{mode:'unset',stages:[],optional_stages:[],definitions:{stages:[]}}};}
function controlledForm(values){
 const error={textContent:''},submit={disabled:false},controls=Object.entries(values).map(([name,value])=>{let current=name==='content'?String(value).replace(/\r\n?/g,'\n'):value;return {name,disabled:false,listeners:{},get value(){return current},set value(v){current=name==='content'?String(v).replace(/\r\n?/g,'\n'):v},addEventListener(t,f){this.listeners[t]=f}}});
 const form={listeners:{},elements:Object.fromEntries(controls.map(c=>[c.name,c])),addEventListener(t,f){this.listeners[t]=f},querySelector:q=>q==='.form-error'?error:submit,querySelectorAll:()=>[...controls,submit]};
 class FormData{constructor(){this.data=new Map(controls.filter(c=>!c.disabled).map(c=>[c.name,c.value]))}get(k){return this.data.get(k)??null}getAll(k){return this.get(k)==null?[]:[this.get(k)]}}
 return {form,error,FormData};
}
function values(a=approved){return {artifact_id:a.artifact_id,title:a.metadata.title,category:'asset',scope:a.scope,chapter:'',episode:'',scene:'',workflow_stage:'',content:a.content,metadata:JSON.stringify(a.metadata),deps:'[]',change_note:'TEST change',asset_type:a.metadata.asset_type||''};}
async function ready(s=snapshot(),options={}){
 const elements=new Map(),listeners={},calls=[],slots=new Map();let handler,document;
 function el(id){if(elements.has(id))return elements.get(id);const e={id,innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,open:false,dataset:{},style:{},scrollTop:0,listeners:{},focus(){document.activeElement=this},scrollIntoView(){},scrollTo(v){this.scrollTop=v.top||0},getBoundingClientRect(){return {top:0,bottom:600,height:600,left:0}},addEventListener(t,f){this.listeners[t]=f},removeEventListener(t){delete this.listeners[t]},setAttribute(n,v){this[n]=v},insertAdjacentHTML(_,h){this.innerHTML+=h},querySelector:q=>id==='editor-content'&&q==='form'?options.form?.form:null,querySelectorAll(q){if(id!=='cards'||q!=='[data-media-thumbnail]'&&q!=='[data-thumbnail-status]')return [];const key=q==='[data-media-thumbnail]'?'mediaThumbnail':'thumbnailStatus',attr=key==='mediaThumbnail'?'media-thumbnail':'thumbnail-status';return [...this.innerHTML.matchAll(new RegExp('data-'+attr+'="([^"]+)"','g'))].map(m=>{const k=key+':'+m[1];if(!slots.has(k))slots.set(k,{dataset:{[key]:m[1]},innerHTML:'',textContent:''});return slots.get(k)});},showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}};elements.set(id,e);return e;}
 document={getElementById:el,activeElement:null,querySelectorAll:()=>Array.from(elements.values()),addEventListener:(t,f)=>listeners[t]=f};
 const catalog={projects:[{...s.project,root:s.project_root}],bindings:[],host_context:{thread_id:'TEST-191-ASSET'}};
 const host={postMessage(message){calls.push(message);if(!message.id)return;Promise.resolve().then(async()=>{try{let result={};if(message.method==='tools/call'){const {name,arguments:args}=message.params;const response=name==='film_board'?{...s,catalog,host_context:catalog.host_context}:options.tool?await options.tool(name,args):name==='film_snapshot'?s:name==='film_history'?{versions:[approved,candidate]}:catalog;result=response?.__raw?response.value:{structuredContent:response};}handler({source:host,data:{jsonrpc:'2.0',id:message.id,result}});}catch(error){handler({source:host,data:{jsonrpc:'2.0',id:message.id,error:{message:error.message}}});}})}};
 const win={scrollY:0,scrollTo(v){this.scrollY=v.top},addEventListener:(t,f)=>{if(t==='message')handler=f},removeEventListener(){}};
 const data=new Map(),context={module:{exports:{}},console,setTimeout,clearTimeout,crypto,document,parent:host,window:win,localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},FormData:options.form?.FormData};
 const insertion='globalThis.__ui={accept,navigateView,renderCards,editCandidate,currentOrderGroup,readContent,history,reviewCandidate,selectReaderVersion,confirmTrash,editCategoryOrder,reader:()=>readerState,journal:()=>journal};';
 const at=source.lastIndexOf('\n}');new vm.Script(source.slice(0,at)+'\n'+insertion+source.slice(at)).runInNewContext(context);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));await tick();await tick();
 return {calls,el,slots,tick,ui:context.__ui,click:dataset=>listeners.click({target:{closest:()=>({dataset})}})};
}
const toolCalls=(f,name)=>f.calls.filter(x=>x.method==='tools/call'&&x.params.name===name).map(x=>x.params.arguments);
const submit=x=>x.form.listeners.submit({preventDefault(){}});
function tomb(a,deleted=true){return {target_type:'artifact',target_id:a.artifact_id,version:a.version,sha256:a.sha256,title:a.metadata.title,kind:a.kind,deleted,revision:1};}

test('asset prompt content tab shows approved, candidate and legacy text without images or media preview calls',async()=>{
 const s=snapshot(),before=JSON.stringify(s),f=await ready(s);f.ui.navigateView('artifacts','asset');await f.tick();
 const cards=f.el('cards').innerHTML,actions=f.el('section-actions').innerHTML;
 assert.match(cards,/TEST 人物制作提示词/);assert.match(cards,/TEST 人物制作提示词待审/);assert.match(cards,/TEST 历史资产文字/);
 assert.equal((cards.match(/data-read="TEST-PROMPT"/g)||[]).length,2);
 assert.doesNotMatch(cards,/TEST-IMAGE-ONLY|TEST 图片原件不可混入提示词|data-preview-image|data-open-image|data-edit-media|已登记图片原件/);
 assert.doesNotMatch(actions,/data-action="import-image"/);assert.match(actions,/data-action="new-artifact"/);
 assert.match(cards,/data-artifact="TEST-PROMPT"/);assert.match(cards,/data-review="TEST-PROMPT"/);
 await f.click({read:approved.artifact_id,version:'1'});const entries=f.ui.reader().entries;
 assert.deepEqual(plain(entries.filter(a=>a.artifact_id===approved.artifact_id).map(a=>a.version).sort()),[1,2]);assert.equal(entries.find(a=>a.artifact_id===approved.artifact_id&&a.version===1).content,BODY);
 assert.ok(entries.some(a=>a.artifact_id===legacy.artifact_id));assert.ok(entries.every(a=>!a.media_id));
 assert.equal(toolCalls(f,'film_media').length,0);assert.equal(toolCalls(f,'film_dispatch').length,0);assert.equal(JSON.stringify(s),before);
});

test('image management sidebar keeps import, low-resolution preview and image classification distinct',async()=>{
 const s=snapshot(),f=await ready(s,{tool:async(name,args)=>name==='film_media'?{media_id:image.media_id,kind:'image',sha256:image.sha256,source_sha256:image.sha256,thumbnail_data_uri:'data:image/png;base64,VEVTVA=='}:s});
 f.ui.navigateView('assets');await f.tick();assert.match(f.el('section-actions').innerHTML,/data-action="import-image"/);
 assert.match(f.el('cards').innerHTML,/data-preview-image="TEST-IMAGE-ONLY"/);assert.match(f.el('cards').innerHTML,/data-edit-media="TEST-IMAGE-ONLY"/);assert.match(f.el('cards').innerHTML,/data-asset-filter="character"/);
 assert.ok(toolCalls(f,'film_media').some(x=>x.action==='preview_image'&&x.payload.media_id===image.media_id));
 assert.equal(f.ui.currentOrderGroup(),'asset_types');assert.equal(toolCalls(f,'film_dispatch').length,0);
});

test('switching from image management to asset prompts stops queued thumbnails and ignores late image output',async()=>{
 const s=snapshot();s.media.push({...plain(image),media_id:'TEST-IMAGE-SECOND',sha256:'e'.repeat(64)});let releasePreview;
 const f=await ready(s,{tool:async(name,args)=>name==='film_media'?new Promise(resolve=>{releasePreview=()=>resolve({media_id:args.payload.media_id,kind:'image',sha256:image.sha256,thumbnail_data_uri:'data:image/png;base64,VEVTVA=='});}):s});
 f.ui.navigateView('assets');await f.tick();assert.equal(toolCalls(f,'film_media').length,1);assert.equal(typeof releasePreview,'function');
 f.ui.navigateView('artifacts','asset');const textView=f.el('cards').innerHTML;releasePreview();await f.tick();await f.tick();
 assert.equal(toolCalls(f,'film_media').length,1);assert.equal(f.el('cards').innerHTML,textView);assert.doesNotMatch(textView,/TEST-IMAGE|data-media-thumbnail|data:image/);
 assert.match(textView,/TEST 人物制作提示词/);assert.equal(toolCalls(f,'film_dispatch').length,0);
});

test('asset prompt tab uses creative category ordering and never changes the image filter order',async()=>{
 const s=snapshot();s.board_order.groups.content_categories={order:['asset','idea','requirements','outline','novel','character_bio','style','source_script','script','director','vfx','video_prompt'],revision:4};
 s.board_order.groups.asset_types={order:['scene','character','prop','other','unclassified'],revision:2};
 let sent;const x=controlledForm({}),f=await ready(s,{form:x,tool:async(name,args)=>{if(name==='film_dispatch'){sent=plain(args);s.board_order.groups[args.payload.group]={order:plain(args.payload.order),revision:args.payload.base_revision+1};return {saved:true}}return s}});f.ui.navigateView('artifacts','asset');
 assert.equal(f.ui.currentOrderGroup(),'content_categories');assert.match(f.el('section-actions').innerHTML,/data-sort-edit="content_categories"/);
 const sub=f.el('subnav').innerHTML;assert.ok(sub.indexOf('data-category="asset"')<sub.indexOf('data-category="idea"'));
 await f.click({sortEdit:'content_categories'});assert.match(f.el('editor-content').innerHTML,/资产提示词/);assert.doesNotMatch(f.el('editor-content').innerHTML,/aria-label="(?:上移人物|下移场景)"/);
 await f.click({sortMove:'asset',direction:'1'});await submit(x);assert.equal(x.error.textContent,'');
 assert.equal(sent.action,'board.order.set');assert.equal(sent.payload.group,'content_categories');assert.equal(sent.payload.base_revision,4);assert.equal(sent.payload.expected_project_id,'TEST-ASSET-191');
 assert.deepEqual(sent.payload.order.slice(0,2),['idea','asset']);assert.deepEqual(s.board_order.groups.asset_types,{order:['scene','character','prop','other','unclassified'],revision:2});
 assert.ok(f.el('subnav').innerHTML.indexOf('data-category="idea"')<f.el('subnav').innerHTML.indexOf('data-category="asset"'));
});

test('new asset prompt editor submits prompt kind, asset category and unchanged entered text',async()=>{
 const x=controlledForm(values({...approved,artifact_id:'TEST-NEW-PROMPT',scope:'TEST/new'})),s=snapshot();let sent;
 const f=await ready(s,{form:x,tool:async(name,args)=>{if(name==='film_dispatch'){sent=plain(args);return {saved:true}}return s}});
 f.ui.navigateView('artifacts','asset');await f.click({action:'new-artifact'});
 assert.match(f.el('editor-content').innerHTML,/<option value="asset" selected>/);assert.doesNotMatch(f.el('editor-content').innerHTML,/name="path"|type="file"/);
 await submit(x);assert.equal(x.error.textContent,'');assert.equal(sent.action,'artifact.save');assert.equal(sent.payload.kind,'prompt');
 assert.equal(sent.payload.metadata.category,'asset');assert.equal(sent.payload.metadata.asset_type,'character');assert.equal(sent.payload.content,BODY);
 assert.equal(sent.payload.base_version,0);assert.equal(sent.payload.expected_project_id,'TEST-ASSET-191');assert.equal(toolCalls(f,'film_media').length,0);assert.equal(f.ui.journal().pending,null);
});

test('editing a legacy asset text keeps its original kind, CRLF body and exact base version',async()=>{
 const original={...legacy,content:'# TEST legacy\r\n\r\n**原文**\r\n'},x=controlledForm(values(original)),s=snapshot();let sent;
 const f=await ready(s,{form:x,tool:async(name,args)=>{if(name==='film_dispatch'){sent=plain(args.payload);return {saved:true}}return s}});
 f.ui.navigateView('artifacts','asset');f.ui.editCandidate(original);await submit(x);
 assert.equal(x.error.textContent,'');assert.equal(sent.kind,'asset');assert.equal(sent.metadata.category,'asset');assert.equal(sent.content,original.content);assert.equal(sent.base_version,1);
 assert.equal(sent.artifact_id,legacy.artifact_id);assert.equal(toolCalls(f,'film_media').length,0);
});

test('prompt review and history retain exact approved and candidate versions without approving on view',async()=>{
 const s=snapshot(),f=await ready(s);f.ui.navigateView('artifacts','asset');await f.click({review:approved.artifact_id});
 assert.equal(f.ui.reader().mode,'review');assert.equal(f.ui.reader().entries.length,1);assert.equal(f.ui.reader().entries[0].version,2);assert.equal(f.ui.reader().baseline.version,1);
 assert.equal(f.ui.reader().entries[0].content,candidate.content);assert.match(f.el('cards').innerHTML,/data-reader-approve/);
 await f.ui.history(approved.artifact_id);f.ui.selectReaderVersion(1);
 assert.equal(f.ui.reader().mode,'history');assert.equal(f.ui.reader().entries[0].version,1);assert.equal(f.ui.reader().entries[0].content,BODY);
 assert.equal(toolCalls(f,'film_dispatch').length,0);assert.equal(toolCalls(f,'film_media').length,0);
});

test('trash and restore hide only the exact prompt version while retaining text metadata and original image records',async()=>{
 const s=snapshot(),before=plain(s),x=controlledForm({}),f=await ready(s,{form:x,tool:async(name,args)=>{
  if(name==='film_dispatch'){const p=args.payload,a=p.version===1?approved:candidate,entry={...tomb(a,p.deleted),revision:p.base_revision+1};s.trash.entries=[entry];const result={entry,readback_verified:true,original_records_retained:true};s.events.push({action:args.action,data:{op_id:p.op_id,result}});return result;}return plain(s);
 }});
 f.ui.navigateView('artifacts','asset');f.ui.confirmTrash('artifact',approved.artifact_id,1,true);assert.match(f.el('editor-content').innerHTML,/不释放磁盘空间/);await submit(x);
 assert.equal(toolCalls(f,'film_dispatch')[0].action,'trash.set');assert.equal(toolCalls(f,'film_dispatch')[0].payload.version,1);
 assert.match(f.el('cards').innerHTML,/TEST 人物制作提示词待审/);assert.equal((f.el('cards').innerHTML.match(/data-read="TEST-PROMPT"/g)||[]).length,1);
 f.ui.navigateView('trash');assert.match(f.el('cards').innerHTML,/TEST 人物制作提示词/);f.ui.confirmTrash('artifact',approved.artifact_id,1,false);await submit(x);
 f.ui.navigateView('artifacts','asset');assert.equal((f.el('cards').innerHTML.match(/data-read="TEST-PROMPT"/g)||[]).length,2);
 assert.deepEqual(s.current_content,before.current_content);assert.deepEqual(s.pending_candidates,before.pending_candidates);assert.deepEqual(s.media,before.media);assert.equal(toolCalls(f,'film_media').length,0);
});

