"""Build-time source transformation of the approved 2.0.0 board. Not a production data migration."""
from pathlib import Path
import re,json
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'plugin/ui/board.html';s=p.read_text('utf-8')
assert "const VERSION='1.20.0';" in s
new=(ROOT/'scripts/board2000-functions.js').read_text('utf8')
for name in ['creatorTaskRows','taskCard1180','renderTasks','renderOverview']:
 s,n=re.subn(r'^function '+name+r'\([^\n]*\n','',s,count=1,flags=re.M);assert n==1,name
import ast
version=next(ast.literal_eval(n.value) for n in ast.parse((ROOT/"filmprod/__init__.py").read_text("utf8")).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="__version__" for t in n.targets))
s=s.replace("const VERSION='1.20.0';",f"const VERSION='{version}';")
s=s.replace("if(typeof module!=='undefined'&&module.exports)",new+"\nif(typeof module!=='undefined'&&module.exports)",1)
s=s.replace('module.exports={BoardFreshness,','module.exports={taskGroup2000,taskLabel2000,overviewCover2000,uiIcon2000,BoardFreshness,',1)
style=s.split('<style>',1)[1].split('</style>',1)[0]
# Functional legacy text remains at a readable floor, including retained auxiliary surfaces.
style=re.sub(r'font-size:(?:9|10)px','font-size:11px',style)
s=s.split('<style>',1)[0]+'<style>'+style+'\n'+(ROOT/'scripts/board2000.css').read_text('utf8')+'\n</style>'+s.split('</style>',1)[1]
s=s.replace('<html lang="zh-CN">','<html lang="zh-CN" data-theme="dark">',1)
s=s.replace('<div class="brand">影视创作<small>让想法成为作品</small></div>','<div class="brand"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M3 12a9 9 0 0 0 18 0Z" fill="currentColor"/></svg><span class="brand-text2000">影视创作<small>让想法成为作品</small></span></div>')
s=s.replace('<nav id="aux-nav" class="nav" aria-label="辅助导航"></nav>','<nav id="aux-nav" class="nav" aria-label="辅助导航"></nav><div class="theme-switch" aria-label="外观"><button data-theme="light" aria-pressed="false">白天</button><button data-theme="dark" aria-pressed="true">夜间</button></div><span class="version-label">VERSION_PLACEHOLDER</span>'.replace("VERSION_PLACEHOLDER",version))
s=s.replace('<button id="refresh" type="button">刷新</button>','<button id="refresh" type="button">刷新</button><button id="quick-theme" type="button" data-action="toggle-theme" aria-label="切换磨砂白日间主题">主题</button>')
s=s.replace('<button id="dialog-close" type="button" aria-label="关闭窗口">关闭</button>','<div class="dialog-controls2000"><button id="dialog-back" type="button" data-action="dialog-back" hidden>返回</button><button id="dialog-close" type="button" aria-label="关闭窗口">关闭</button></div>')
s=s.replace('const PAGE_SIZE=12;','const PAGE_SIZE=12;\n'+(ROOT/'scripts/board2000-runtime.js').read_text('utf8'),1)
s=s.replace('query:creatorTaskQuery})','query:creatorTaskQuery,layout:taskLayout2000})')
s=s.replace('>${label}</button>`).join(\'\');el(\'aux-nav\')','>${uiIcon2000(id)}${label}</button>`).join(\'\');el(\'aux-nav\')',1)
s=s.replace("if(d.stage){creatorStage=d.stage;view='tasks';render();return true;}","if(d.taskLayout){taskLayout2000=d.taskLayout==='board'?'board':'list';render();return true;}if(d.stage){creatorStage=d.stage;view='tasks';render();resetScroll2000();return true;}")
s=s.replace("if(d.object){objectId=d.object;view='media';render();return true;}","if(d.object){objectId=d.object;view='media';render();resetScroll2000();return true;}")
s=s.replace("case 'creator-back':objectId=null;render();return true;","case 'creator-back':objectId=null;render();resetScroll2000();return true;")
s=s.replace("selected.clear();render();requestFreshness();}","selected.clear();render();resetScroll2000();requestFreshness();}",1)
show="""function show(title,html){if(/<form(?:\\s|>)/i.test(html)&&(journal?.pending||journal?.busy))throw new Error('请先核对未完成的管理操作，再打开新的设置窗口。');if(el('dialog').open&&dialogDirty)throw new Error('当前窗口有未保存的资料设置，请先保存或关闭。');if(dialogClosing2000)throw new Error('窗口正在关闭，请稍后重试。');const d=el('dialog'),body=el('dialog-body');if(d.open&&!previsActive&&!body.innerHTML.includes('id="pv-camera"')&&!/<form(?:\\s|>)/i.test(body.innerHTML))dialogTrail2000.push(saveDialog2000());else if(!d.open)dialogTrail2000=[];dialogSession++;dialogOrigin=capture();dialogDirty=false;el('dialog-title').textContent=title;body.innerHTML=html;body.scrollTop=0;d.classList?.toggle('reader-drawer2000',html.includes('<article class="prose">'));dialogBackButton2000();if(!d.open)d.showModal();el('dialog-close').focus();renderCatalog();return dialogSession;}"""
s,n=re.subn(r'^function show\([^\n]*',lambda m:show,s,count=1,flags=re.M);assert n==1
close="""function closeDialog(){if(dialogDirty&&!window.confirm('关闭后，本次未保存的资料设置会丢弃。'))return;if(dialogClosing2000)return;dialogDirty=false;dialogSession++;dialogTrail2000=[];disposePrevis();const d=el('dialog'),finish=()=>{d.close();dialogClosing2000=false;dialogBackButton2000();renderCatalog();};if(d.animate&&!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches&&!document.body?.classList?.contains('keyboard2000')){dialogClosing2000=true;const a=d.animate([{opacity:1},{opacity:0}],{duration:140,easing:'ease-out'});a.onfinish=()=>{finish();a.cancel();};}else finish();}"""
s,n=re.subn(r'^function closeDialog\([^\n]*',lambda m:close,s,count=1,flags=re.M);assert n==1
s=s.replace("const d=button.dataset;if(d.previs)","const d=button.dataset;if(d.theme){setTheme2000(d.theme);return;}if(d.action==='toggle-theme'){setTheme2000(theme2000==='dark'?'light':'dark');return;}if(d.action==='dialog-back')return backDialog2000();if(d.previs)",1)
s=s.replace("if(action==='close-dialog')return closeDialog();","if(action==='close-dialog')return backDialog2000();")
s=s.replace("el('dialog').addEventListener('close',()=>{disposePrevis();","el('dialog').addEventListener('close',()=>{dialogTrail2000=[];dialogBackButton2000();disposePrevis();")
s=s.replace("void initialize();","initAppearance2000();\nvoid initialize();",1)
# Show exact version and review state in the real reader.
s=s.replace("${item.legacy_archived?badge('','旧版归档记录'):''}</div><p class=\"dim\">${esc(scopeLabel(item.scope))}","${item.legacy_archived?badge('','旧版归档记录'):''}${item.review_status==='needs_review'?badge('needs_review'):''}</div><div class=\"reference-versions2000\"><span>阅读版本 <strong>v${version}</strong></span><span>最新候选 <strong>${item.latest_working_version?'v'+esc(item.latest_working_version):'未记录'}</strong></span><span>采用版本 <strong>${item.latest_adopted_version?'v'+esc(item.latest_adopted_version):'未记录'}</strong></span></div><p class=\"dim\">${esc(scopeLabel(item.scope))}")
s=s.replace("const obj=objectsFor(state).find(o=>o.object_id===link.object_id),old=selectionFor(state,link.object_id,link.purpose);show(","const obj=objectsFor(state).find(o=>o.object_id===link.object_id),old=selectionFor(state,link.object_id,link.purpose),oldItem=old&&snapshotItems(state).find(i=>i.target_type===old.reference.target_type&&i.target_id===old.reference.target_id&&(i.version||null)===(old.reference.version||null)&&i.sha256===old.reference.sha256);show(")
s=s.replace('<h3>${esc(item.title)}</h3></div><p>只更新这个对象的对应用途。','<h3>${esc(item.title)}</h3><p>当前选用：${esc(oldItem?.title||(old?\'原素材记录待核对\':\'尚未选用\'))} → ${esc(item.title)}</p></div><p>只更新这个对象的对应用途。',1)
s=s.replace('data-pv-mode="camera">','data-pv-mode="camera" aria-pressed="true">').replace('data-pv-mode="top">','data-pv-mode="top" aria-pressed="false">').replace('data-pv-mode="dual">','data-pv-mode="dual" aria-pressed="false">')
s=s.replace("mode=node.dataset.pvMode;cam.hidden", "mode=node.dataset.pvMode;for(const b of el('dialog-body').querySelectorAll('[data-pv-mode]'))b.setAttribute('aria-pressed',String(b===node));cam.hidden")
# Homepage filters are local state, distinct from task-page navigation.
s=s.replace('overview:()=>renderOverview(state)','overview:()=>renderOverview(state,overviewStage2001)')
s=s.replace("async function creatorAction(d){", "async function creatorAction(d){if(d.overviewStage){if(view!=='overview'||(d.overviewStage!=='all'&&!CREATIVE_STAGES.some(s=>s[0]===d.overviewStage)))return true;overviewStage2001=d.overviewStage==='all'?'':d.overviewStage;render();document.querySelector?.('[data-overview-stage=\"'+d.overviewStage+'\"]')?.focus({preventScroll:true});return true;}")
s=s.replace("epoch++;objectId=null;creatorTaskScope='';", "epoch++;overviewStage2001='';objectId=null;creatorTaskScope='';")
p.write_text(s,encoding='utf8',newline='\n')
print('Built board',version)
