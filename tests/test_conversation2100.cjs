const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../plugin/ui/board.html'),'utf8');
const context={module:{exports:{}},console,setTimeout,clearTimeout};
new vm.Script(html.split('<script>')[1].split('</script>')[0]).runInNewContext(context);
const h=context.module.exports;
test('submitted task remains a candidate with completion still pending',()=>{
 const text=h.conversationRows([{title:'TEST 合成专题',kind:'execution',scope:'episode/1',status:'task_bound',task_id:'TEST-T',task_status:'submitted',task_output_ref:{artifact_id:'TEST-A',version:1},needs_completion_record:true,completion_recorded:false,report_status:'not_ready'}]);
 assert.match(text,/任务已提交候选/);assert.match(text,/完成待登记/);assert.match(text,/候选成果：TEST-A/);
 assert.doesNotMatch(text,/完成已登记|回报已由宿主接收|已批准/);
});
test('completion and outbound authorization remain distinct and read only',()=>{
 const text=h.conversationRows([{title:'TEST',kind:'execution',scope:'episode/1',status:'completed',completion_recorded:true,report_status:'pending_authorization',thread_id:'TEST-CHAT'}]);
 assert.match(text,/完成已登记/);assert.match(text,/回报待授权/);assert.match(text,/data-open-thread="TEST-CHAT"/);
 assert.doesNotMatch(text,/data-(?:send|claim|complete|report|approve|create)/);
});
test('host receipt does not imply business processing and unknown stays unknown',()=>{
 assert.match(h.conversationRows([{status:'completed',report_status:'host_accepted'}]),/不代表接收方完成处理或用户批准/);
 const text=h.conversationRows([{title:'<script>TEST</script>',status:'completed',report_status:'unknown'}]);
 assert.match(text,/回报结果未知/);assert.match(text,/&lt;script&gt;/);assert.doesNotMatch(text,/<script>/);
});
