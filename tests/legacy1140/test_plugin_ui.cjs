const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
const releaseVersion=fs.readFileSync(path.join(__dirname,'../filmprod/__init__.py'),'utf8').match(/__version__\s*=\s*["']([^"']+)["']/)[1];
const sandbox={module:{exports:{}},console,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto};
new vm.Script(source,{filename:'plugin/ui/board.html'}).runInNewContext(sandbox);
const {listValue,refsValue,checkpointPayload,taskPayload,submitPayload,renderPayload,outputKinds,unwrap,RpcBridge,WriteJournal:RawWriteJournal,lineDiff}=sandbox.module.exports;
class WriteJournal extends RawWriteJournal{
 constructor(options){const read=options.read;super({...options,ownerContext:{thread_id:'TEST-UNIT-CHAT'},read:async(...args)=>{const snap=await read(...args);return snap.operations?snap:{...snap,project:snap.project||{project_id:'TEST-UNIT-PROJECT'}};}});}
 run(root,action,payload,toolName='film_dispatch'){return super.run(root,action,{...payload,...(toolName==='film_projects'?{}:{expected_project_id:payload.expected_project_id||'TEST-UNIT-PROJECT'})},toolName);}
}
const plain=x=>JSON.parse(JSON.stringify(x));
const form=data=>new Map(Object.entries(data));
function storage(){const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};}
function fakeBridge(){let handler;const sent=[],host={postMessage:m=>sent.push(m)},listener={addEventListener:(_,fn)=>handler=fn,removeEventListener:()=>handler=null};let timer;const clock={setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{timer=null;}};return {sent,host,listener,clock,emit:(data,source=host)=>handler?.({source,data}),expire:()=>timer?.()};}

test('checkpoint retains JSON arrays, structured decisions, complete prose and empty unknown lists',()=>{
 const p=plain(checkpointPayload(form({draft:'全文\n对白：“灯还亮着。”',completed:'["镜1完成"]',decisions:'[{"source":"test","decision":"仅测试"}]',unresolved:'',next_step:'复核'}),'TASK-1'));
 assert.deepEqual(p.completed,['镜1完成']);assert.deepEqual(p.decisions,[{source:'test',decision:'仅测试'}]);assert.deepEqual(p.unresolved,[]);assert.equal(p.draft,'全文\n对白：“灯还亮着。”');assert.deepEqual(plain(listValue('甲\r\n\r\n 乙')),['甲','乙']);
 assert.throws(()=>listValue('[bad]'));assert.throws(()=>listValue('[1]'));assert.throws(()=>listValue('{}'));
});
test('new task payload locks target and exact inputs without upgrading versions',()=>{
 const p=plain(taskPayload(form({task_id:'T2',title:'导演修订',module:'director',scope:'S03',artifact_id:'DIR-S03',thread_id:'chat-1',inputs:'[{"artifact_id":"SCRIPT-S03","version":2}]',must_keep:'对白\n伞',allowed_changes:'["灯光"]',requirements:'["完整方案"]'})));
 assert.deepEqual(p.inputs,[{artifact_id:'SCRIPT-S03',version:2}]);assert.equal(p.artifact_id,'DIR-S03');assert.deepEqual(p.must_keep,['对白','伞']);assert.equal(p.thread_id,'chat-1');
 for(const value of ['[{"artifact_id":"A","version":0}]','[{"artifact_id":"A","version":"2"}]','{}'])assert.throws(()=>refsValue(value));
});
test('task submission respects module, locked ID, scope and captured base; never records adoption',()=>{
 const t={task_id:'T3',module:'director-agent',artifact_id:'DIR-S03',scope:'S03'},known=[{artifact_id:'DIR-S03',kind:'director',scope:'S03',version:4}],data={artifact_id:'DIR-S03',kind:'director',base_version:'4',format:'json',content:'{"shots":["全景"]}',metadata:'{"source":"snapshot"}',change_note:'补调度'};
 const p=plain(submitPayload(form(data),t,known));assert.equal(p.base_version,4);assert.equal(p.task_id,'T3');assert.deepEqual(p.content,{shots:['全景']});assert.equal(p.metadata.local_candidate,true);assert.equal(p.metadata.authority,'local candidate');assert.equal(p.decision,undefined);
 assert.throws(()=>submitPayload(form({...data,kind:'script'}),t,known));assert.throws(()=>submitPayload(form({...data,artifact_id:'OTHER'}),t,known));assert.throws(()=>submitPayload(form({...data,base_version:'5'}),t,known));assert.throws(()=>submitPayload(form(data),{...t,scope:'S04'},known));
 assert.deepEqual(plain(outputKinds('new-module',{module_output_kinds:{'new-module':['custom_kind']}})),['custom_kind']);
});
test('MCP result decoding preserves explicit tool rejection and rejects unreadable results',()=>{
 assert.deepEqual(plain(unwrap({structuredContent:{ok:true}})),{ok:true});assert.deepEqual(plain(unwrap({content:[{type:'text',text:'{"ok":true}'}]})),{ok:true});
 assert.throws(()=>unwrap({isError:true,content:[{type:'text',text:'ConflictError: old base'}]}),e=>e.knownRejected===true);
 assert.throws(()=>unwrap({isError:true,content:[{type:'text',text:'RuntimeError: unknown completion'}]}),e=>e.knownRejected===false);
 assert.throws(()=>unwrap({content:[{type:'text',text:'not json'}]}));
});
test('bridge accepts only matching parent responses; surfaces notifications and RPC errors',async()=>{
 const f=fakeBridge(),errors=[],bridge=new RpcBridge(f.host,f.listener,{clock:f.clock,onNotification:()=>{throw new Error('bad notification');},onError:e=>errors.push(e.message)});
 const p=bridge.request('tools/call',{name:'film_history',arguments:{root:'F:/TEST',artifact_id:'A'}}),id=f.sent[0].id;
 f.emit({jsonrpc:'2.0',id,result:{wrong:true}},{});assert.equal(bridge.waiting.size,1);
 f.emit({jsonrpc:'2.0',id,result:{versions:[]}});assert.deepEqual(await p,{versions:[]});
 f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{}});assert.deepEqual(errors,['bad notification']);
 const rejected=bridge.request('tools/call',{});f.emit({jsonrpc:'2.0',id:f.sent[1].id,error:{message:'host denied'}});await assert.rejects(rejected,/host denied/);bridge.close();
});
test('bridge timeout reports unknown and ignores late responses',async()=>{
 const f=fakeBridge(),bridge=new RpcBridge(f.host,f.listener,{clock:f.clock});const p=bridge.request('tools/call',{name:'film_dispatch'});const check=assert.rejects(p,e=>e.unknown===true);f.expire();await check;assert.equal(bridge.waiting.size,0);f.emit({jsonrpc:'2.0',id:f.sent[0].id,result:{ok:true}});assert.equal(bridge.waiting.size,0);bridge.close();
});
test('unknown write survives reload and retries exactly the original payload and op_id',async()=>{
 const store=storage(),calls=[],payload={task_id:'TASK-1',draft:'原稿',completed:[],decisions:[],unresolved:[],next_step:'继续'};
 const first=new WriteJournal({storage:store,makeId:()=> 'OP-FIXED',call:async req=>{calls.push(plain(req));throw new Error('timeout');},read:async()=>({events:[]})});
 await assert.rejects(first.run('F:/TEST','task.checkpoint',payload),/timeout/);payload.draft='后来改动不可覆盖原请求';assert.equal(first.pending.phase,'unknown');
 await assert.rejects(first.run('F:/TEST','task.checkpoint',payload),/先核对/);
 const second=new WriteJournal({storage:store,makeId:()=>{throw new Error('must not make new op');},call:async req=>{calls.push(plain(req));return {saved:true};},read:async()=>({events:[{data:{op_id:'OP-FIXED'}}]})});
 await second.retry();assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].payload.draft,'原稿');assert.equal(second.pending,null);assert.equal(store.getItem(second.key),null);
});
test('acknowledged write with failed readback only rereads on retry, never redispatches',async()=>{
 const store=storage();let writes=0;
 const first=new WriteJournal({storage:store,makeId:()=> 'OP-ACK',call:async()=>{writes++;return {saved:true};},read:async()=>{throw new Error('read failed');}});
 await assert.rejects(first.run('F:/TEST','task.cancel',{task_id:'T',reason:'重新绑定输入'}),/read failed/);assert.equal(first.pending.phase,'acknowledged');
 const second=new WriteJournal({storage:store,call:async()=>{writes++;throw new Error('should not send');},read:async()=>({events:[]})});
 await second.retry();assert.equal(writes,1);assert.equal(second.pending,null);
});
test('read-only unknown recovery requires a matching operation event',async()=>{
 const store=storage();let confirmed=false,writes=0;
 const journal=new WriteJournal({storage:store,makeId:()=> 'OP-UNKNOWN',call:async()=>{writes++;throw new Error('connection lost');},read:async()=>({events:confirmed?[{data:{op_id:'OP-UNKNOWN',result:{saved:true}}}]:[]})});
 await assert.rejects(journal.run('F:/TEST','artifact.save',{artifact_id:'A',base_version:0}));await assert.rejects(journal.verify(),/尚不能确认/);assert.ok(journal.pending);confirmed=true;const result=await journal.verify();assert.deepEqual(result.result,{saved:true});assert.equal(writes,1);assert.equal(journal.pending,null);
});
test('explicit rejection clears pending but arbitrary adoption action is forbidden',async()=>{
 const journal=new WriteJournal({storage:storage(),makeId:()=> 'OP-REJECT',call:async()=>{const e=new Error('ConflictError: old version');e.knownRejected=true;throw e;},read:async()=>({events:[]})});
 await assert.rejects(journal.run('F:/TEST','task.submit',{task_id:'T'}),/old version/);assert.equal(journal.pending,null);await assert.rejects(journal.run('F:/TEST','decision.record',{decision:'adopt'}),/不允许/);
});
test('storage failure is exposed, and prepared request is retained in memory for copying',async()=>{
 const store={getItem:()=>null,setItem:()=>{throw new Error('blocked');},removeItem:()=>{}};const journal=new WriteJournal({storage:store,makeId:()=> 'COPY-ME',call:async()=>{throw new Error('unknown');},read:async()=>({events:[]})});await assert.rejects(journal.run('F:/TEST','cue.save',{cue_id:'C'}));assert.equal(journal.persisted,false);assert.equal(JSON.parse(journal.pending.requestJSON).payload.op_id,'COPY-ME');
});
test('UI is standalone MCP resource with semantic controls and no network client',()=>{
 assert.ok(html.includes('项目工作台 · '+releaseVersion));assert.ok(source.includes("name:'film-production-agent-board',version:'"+releaseVersion+"'"));assert.ok(html.includes('aria-label="作品绝对目录"'));assert.ok(html.includes('aria-labelledby="editor-title"'));assert.ok(html.includes("'film_history'"));assert.ok(html.includes("'task.submit'"));assert.ok(html.includes("'cue.save'"));assert.ok(!/\bfetch\s*\(|XMLHttpRequest|new\s+WebSocket|localhost|127\.0\.0\.1/.test(source));assert.ok(!/<script[^>]+src=|<link[^>]+href=/.test(html));
 assert.deepEqual(plain(lineDiff('同一行\n旧句\n末尾','同一行\n新句\n末尾')).filter(x=>x.kind),[{kind:'del',text:'旧句'},{kind:'add',text:'新句'}]);
});
test('render form binds a known exact final and forces TEST preview regardless of control value',()=>{
 const versions=[{artifact_id:'FINAL-1',version:1,kind:'final'},{artifact_id:'FINAL-1',version:2,kind:'final'}];
 assert.deepEqual(plain(renderPayload(form({artifact_id:'FINAL-1',version:'1',preview:'false'}),true,versions)),{artifact_id:'FINAL-1',version:1,preview:true});
 assert.equal(renderPayload(form({artifact_id:'FINAL-1',version:'2',preview:'false'}),false,versions).preview,false);
 assert.throws(()=>renderPayload(form({artifact_id:'FINAL-1',version:'3',preview:'true'}),true,versions));
 assert.throws(()=>renderPayload(form({artifact_id:'SCRIPT-1',version:'1'}),true,[{artifact_id:'SCRIPT-1',version:1,kind:'script'}]));
});
test('render retries retain toolName, source version, preview and operation ID across reload',async()=>{
 const store=storage(),calls=[];
 const first=new WriteJournal({storage:store,makeId:()=> 'RENDER-OP',call:async req=>{calls.push(plain(req));throw new Error('render timeout');},read:async()=>({events:[]})});
 await assert.rejects(first.run('F:/TEST','render',{artifact_id:'FINAL-1',version:2,preview:true},'film_render'));
 const second=new WriteJournal({storage:store,makeId:()=>{throw new Error('new op forbidden');},call:async req=>{calls.push(plain(req));return {render_id:'R',preview:true};},read:async()=>({events:[]})});
 const out=await second.retry();assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].toolName,'film_render');assert.equal(out.toolName,'film_render');assert.equal(out.result.render_id,'R');assert.equal(second.pending,null);
});
test('render partial-media event cannot be mistaken for a completed render result',async()=>{
 let completed=false;const journal=new WriteJournal({storage:storage(),makeId:()=> 'RENDER-EVENT',call:async()=>{throw new Error('timeout');},read:async()=>({events:[{data:{op_id:completed?'RENDER-EVENT:render-result':'RENDER-EVENT:render-media',result:completed?{artifact:{content:{render_id:'RENDER-FINAL',preview:true}}}:{media_id:'PARTIAL'}}}]})});
 await assert.rejects(journal.run('F:/TEST','render',{artifact_id:'F',version:1,preview:true},'film_render'));await assert.rejects(journal.verify(),/尚不能确认/);assert.ok(journal.pending);completed=true;const out=await journal.verify();assert.equal(out.result.render_id,'RENDER-FINAL');assert.equal(journal.pending,null);
});
test('render errors retain original request because output or partial job may already exist',async()=>{
 const journal=new WriteJournal({storage:storage(),makeId:()=> 'RENDER-PARTIAL',call:async()=>{const e=new Error('ConflictError: inputs changed after encode');e.knownRejected=true;throw e;},read:async()=>({events:[]})});
 await assert.rejects(journal.run('F:/TEST','render',{artifact_id:'F',version:1,preview:true},'film_render'));assert.equal(journal.pending.phase,'unknown');assert.equal(JSON.parse(journal.pending.requestJSON).toolName,'film_render');
});
test('render releases the journal only for an explicit backend no-effect outcome',async()=>{
 for(const outcome of ['no_write','failed_before_commit','unknown','resumable',undefined]){
  const journal=new WriteJournal({storage:storage(),makeId:()=> 'RENDER-EXPLICIT',call:async()=>unwrap({isError:true,content:[{type:'text',text:'ValueError: unsupported output'}],structuredContent:{error:{type:'ValueError',message:'unsupported output',operation_outcome:outcome}}}),read:async()=>({events:[]})});
  await assert.rejects(journal.run('F:/TEST','render',{artifact_id:'F',version:1,preview:true},'film_render'));
  if(['no_write','failed_before_commit'].includes(outcome))assert.equal(journal.pending,null);
  else assert.equal(journal.pending.phase,'unknown');
 }
});
test('a snapshot from another project never confirms a write even when op_id matches',async()=>{
 const journal=new WriteJournal({storage:storage(),makeId:()=> 'CROSS-PROJECT',call:async()=>({ok:true}),read:async()=>({project_root:'F:/OTHER',events:[{data:{op_id:'CROSS-PROJECT'}}]})});
 await assert.rejects(journal.run('F:/TEST','task.cancel',{task_id:'T',reason:'test'}),/不同项目/);assert.equal(journal.pending.phase,'acknowledged');assert.equal(JSON.parse(journal.pending.requestJSON).root,'F:/TEST');
});
