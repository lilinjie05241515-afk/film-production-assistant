"use strict";
// Legacy compatibility page: no writable request, chat action or generic dispatch.
const esc = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function read(path) { const r=await fetch(path,{method:"GET"});const data=await r.json();if(!r.ok)throw Error(data.error||"查询失败");return data; }
async function refresh(){try{const project=document.querySelector("#project").value;if(!project)return;const snap=await read("/api/snapshot?project="+encodeURIComponent(project));document.querySelector("#content").innerHTML=(snap.artifacts||[]).map(a=>`<article><h2>${esc(a.metadata?.title||a.artifact_id)}</h2><p>${esc(a.artifact_id)} · v${esc(a.version)} · ${esc(a.scope)}</p><pre>${esc(typeof a.content==="string"?a.content:JSON.stringify(a.content,null,2))}</pre></article>`).join("");document.querySelector("#status").textContent="已读取记录；本入口不会执行创作或修改资料。";}catch(e){document.querySelector("#status").textContent=e.message;}}
async function start(){try{const catalog=await read("/api/projects");document.querySelector("#project").innerHTML=(catalog.projects||[]).map(p=>`<option value="${esc(p.key)}">${esc(p.title)}</option>`).join("");await refresh();}catch(e){document.querySelector("#status").textContent=e.message;}}
if(typeof document!=="undefined"){document.querySelector("#refresh").addEventListener("click",refresh);document.querySelector("#project").addEventListener("change",refresh);start();}
if(typeof module!=="undefined")module.exports={esc};
