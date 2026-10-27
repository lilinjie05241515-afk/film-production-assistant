function previsForTask(snap,task){return asList(snap.previs?.series).filter(s=>s.task_id===task.task_id);}
function previsShot(manifest,time){return asList(manifest?.shots).find(s=>time>=s.start/manifest.fps&&time<s.end/manifest.fps)||asList(manifest?.shots).at(-1);}
function previsFeedbackText(s,v,shot,time,quote){return `预演 ${s.previs_id} / v${v.version} / ${v.sha256}\n镜头 ${shot.id} / ${time.toFixed(3)} 秒\n${quote}`;}
function previsTaskButtons(snap,task){return previsForTask(snap,task).map(s=>`<button class="primary small" data-previs="${esc(s.previs_id)}">预演审看 · ${esc(s.title)}</button>`).join('');}
