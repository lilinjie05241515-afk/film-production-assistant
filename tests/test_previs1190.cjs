const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');const source=html.split('<script>')[1].split('</script>')[0];
const ctx={module:{exports:{}},console};new vm.Script(source).runInNewContext(ctx);const h=ctx.module.exports;
test('previs gateway only exposes read, chunk, feedback and exact select to board',()=>{
 for(const x of ['previs.read','previs.chunk','previs.feedback','previs.select'])assert(h.ALL_ACTIONS.has(x));
 for(const x of ['previs.register','previs.render','task.create','conversation.send'])assert(!h.ALL_ACTIONS.has(x));
});
test('half-open shot lookup handles cut and end position without changing IDs',()=>{
 const m={fps:12,shots:[{id:'SH010',start:0,end:72},{id:'SH020',start:72,end:240}]};
 assert.equal(h.previsShot(m,5.999).id,'SH010');assert.equal(h.previsShot(m,6).id,'SH020');assert.equal(h.previsShot(m,20).id,'SH020');
});
test('feedback copy preserves exact quote and source version',()=>{
 const quote='  机位\n调整  ',text=h.previsFeedbackText({previs_id:'S01'},{version:2,sha256:'exact-hash'},{id:'SH020'},8.125,quote);
 assert(text.endsWith(quote));assert(text.includes('v2 / exact-hash'));assert(text.includes('SH020 / 8.125'));
});
test('previs appears only under linked task, and titles escape HTML',()=>{
 const snap={previs:{series:[{previs_id:'S01',task_id:'T1',title:'<script>alert(1)</script>'}]}};
 assert.equal(h.previsForTask(snap,{task_id:'T2'}).length,0);
 assert(!h.previsTaskButtons(snap,{task_id:'T1'}).includes('<script>'));assert(h.previsTaskButtons(snap,{task_id:'T1'}).includes('data-previs="S01"'));
});
