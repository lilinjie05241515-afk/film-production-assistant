const freshnessStatus=()=>el('freshness-status');
const updateClock=d=>d?d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}):'尚未更新';
function freshnessBlocked(){const active=document.activeElement;return Boolean(projectLoading||journal?.pending||journal?.busy||el('dialog').open||dialogDirty||active&&['INPUT','TEXTAREA','SELECT'].includes(active.tagName));}
function freshnessApply(snap,token){
 const scrollX=window.scrollX||0,scrollY=window.scrollY||0,selection=[...selected],oldId=state?.project?.project_id;
 if(token.registered&&!asList(snap.catalog?.projects).some(p=>p.project_id===token.project_id)){
  if(rootIdentity(snap.project_root)!==token.root||snap.project?.project_id!==token.project_id)throw new Error('项目身份已变化');
  snap={...snap,project:null,project_root:null};accept(snap);window.scrollTo?.(scrollX,scrollY);return;
 }
 accept(snap,{expectedRoot:token.root||null,expectedId:token.project_id||null});
 if(oldId===state?.project?.project_id){for(const key of selection)if(itemByKey(key))selected.add(key);if(selection.length)render();}
 window.scrollTo?.(scrollX,scrollY);
}
const freshnessMonitor=new BoardFreshness({
 version:VERSION,ready:()=>connected,visible:()=>document.visibilityState!=='hidden',
 capture:()=>({...capture(),registered:asList(catalog.projects).some(p=>p.project_id===state?.project?.project_id)}),current:isCurrent,blocked:freshnessBlocked,
 poll:t=>call('board.poll',t.root?{expected_project_id:t.project_id}:context(),t.root),
 read:t=>call('snapshot',t.root?{expected_project_id:t.project_id}:context(),t.root),
 apply:freshnessApply,
 status:s=>{const node=freshnessStatus();if(!node)return;const last=s.lastUpdated?' · 最近更新 '+updateClock(s.lastUpdated):'';node.textContent=({updated:'已更新',checked:'已检查',pending:'有新内容，结束当前操作后更新',loading:'正在更新…',error:'更新失败，点击刷新重试',upgrade:'插件已升级，请关闭并重新打开看板'})[s.kind]+last;node.dataset.state=s.kind;}
});
let freshnessTimer=null,freshnessStopped=false;
function scheduleFreshness(){if(freshnessStopped||freshnessTimer)return;freshnessTimer=setTimeout(async()=>{freshnessTimer=null;await freshnessMonitor.check();scheduleFreshness();},Math.min(30000,5000*2**Math.min(freshnessMonitor.failures,3)));freshnessTimer?.unref?.();}
function requestFreshness(){if(connected)void freshnessMonitor.check();}
document.addEventListener('visibilitychange',requestFreshness);
window.addEventListener('focus',requestFreshness);
document.addEventListener('focusout',()=>{if(freshnessMonitor.pending)setTimeout(requestFreshness,0);});
window.addEventListener('pagehide',()=>{freshnessStopped=true;clearTimeout(freshnessTimer);freshnessTimer=null;});
window.addEventListener('pageshow',()=>{freshnessStopped=false;scheduleFreshness();requestFreshness();});
