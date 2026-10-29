// Read-only progress derived from exact task and host request observations.
function conversationProgress(topic){
 const labels=[];
 if(topic.task_status==='submitted')labels.push('任务已提交候选');
 else if(topic.task_status)labels.push('任务：'+(STATUS_LABELS[topic.task_status]||topic.task_status));
 if(topic.needs_completion_record)labels.push('完成待登记');
 else if(topic.completion_recorded)labels.push('完成已登记');
 const reports={pending_authorization:'回报待授权',planned:'回报待发送',in_flight:'回报结果待核对',queued:'回报排队中',unknown:'回报结果未知',failed:'回报待处理',cancelled:'回报已取消',host_accepted:'回报已由宿主接收'};
 if(reports[topic.report_status])labels.push(reports[topic.report_status]);
 return labels;
}
function conversationRows(topics){return topics.map(t=>{
 const ref=t.output_ref||t.task_output_ref;
 const progress=conversationProgress(t);
 return `<div class="record-row topic-row"><div class="record-main"><strong>${esc(t.title||'未命名专题')}</strong><small>${esc(t.kind==='idea'?'灵感讨论':'创作执行')} · ${esc(scopeLabel(t.scope))}</small><div class="badges">${badge('',conversationLabel(t.status))}${progress.map(label=>badge('',label)).join('')}${t.task_id&&!t.task_status?badge('','已关联创作任务'):''}</div>${ref?`<small>候选成果：${esc(ref.artifact_id)} · 第 ${esc(ref.version)} 版</small>`:''}${t.report_status==='host_accepted'?'<small>消息已接收不代表接收方完成处理或用户批准。</small>':''}</div>${t.thread_id?`<button class="small" data-open-thread="${esc(t.thread_id)}">打开对话 ↗</button>`:'<small>尚无已核对的对话</small>'}</div>`;
 }).join('');}
