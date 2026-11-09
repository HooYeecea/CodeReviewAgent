"use strict";
const token = location.hash.slice(1);
const $ = id => document.getElementById(id);
let state = null, busy = false, closed = false;
const labels = {unchecked:"未验证",still_present:"仍存在",resolved:"已解决",uncertain:"无法确认"};
const phases = {choose:"请选择报告",selected:"等待验证问题",validating:"正在验证",validated:"可以选择问题",validation_failed:"问题验证失败，可重试",preview:"等待确认补丁",applying:"正在应用",applied:"已应用，等待复审",verified:"模型复审未发现遗留问题，请运行项目测试",needs_attention:"仍有问题需要处理",verification_failed:"复审失败，可重新验证",rolled_back:"应用失败，已回滚",recovery_required:"需要人工恢复，请检查记录和备份"};
function node(tag, text) { const e=document.createElement(tag); e.textContent=text; return e; }
async function api(path, body) {
  const response = await fetch('/api/'+path, {method:body===undefined?'GET':'POST',headers:{'X-Gai-Token':token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(data.error || '操作失败'); return data;
}
function controls() {
  document.querySelectorAll('button,select,input').forEach(e=>e.disabled=busy||closed);
  if(busy || closed || !state) return;
  $('validate').disabled=!state.report || ['applied','verified','verification_failed','needs_attention','recovery_required'].includes(state.phase);
  $('generate').disabled=!['validated','preview'].includes(state.phase);
  $('apply').disabled=state.phase!=='preview';
  $('verify').disabled=!['applied','verified','verification_failed','needs_attention'].includes(state.phase);
  document.querySelectorAll('[data-issue]').forEach(e=>{const i=state.findings.find(i=>i.id===Number(e.dataset.issue));e.disabled=i.status!=='still_present'||!!i.blocked;});
}
function render(s) {
  state=s;
  $('phase').textContent='当前阶段：'+(phases[s.phase]||s.phase);
  $('note').textContent=s.note;
  $('reports').replaceChildren(...s.reports.map(r=>{const o=node('option',r.title+' · '+r.id.slice(0,8));o.value=r.id;o.selected=s.report?.id===r.id;return o;}));
  $('findings').replaceChildren();
  for(const i of s.findings){
    const div=node('div','');div.className='finding';const label=node('label','');const check=document.createElement('input');check.type='checkbox';check.dataset.issue=i.id;
    label.append(check,document.createTextNode(` ${i.id}. [${i.severity}] ${i.file}:${i.line??'—'} · ${labels[i.status]||i.status}`));div.append(label);
    for(const text of [i.issue,'建议：'+i.suggestion,'验证：'+i.reason,i.blocked]) if(text) div.append(node('p',text));
    const button=node('button','查看代码');button.onclick=()=>action(async()=>{const data=await api('code',{id:i.id});$('code').textContent=data.note+'\n\n'+data.code;});div.append(button);$('findings').append(div);
  }
  $('patch').replaceChildren();
  for(const file of s.proposal?.files||[]) $('patch').append(node('h3',file.file+' · 问题 '+file.issue_ids.join(', ')),node('pre',file.diff));
  for(const i of s.proposal?.unresolved||[]) $('patch').append(node('p',`未解决 ${i.id}：${i.reason}`));
  const v=s.verification;
  $('verification').textContent=v?[
    ...v.checks.map(i=>`问题 ${i.id} · ${labels[i.status]||i.status}：${i.reason}`),
    ...(v.new_findings||[]).map(i=>`新增 [${i.severity}] ${i.file}:${i.line??'—'}\n${i.issue}\n建议：${i.suggestion}`),
    v.tests||'',v.note||''
  ].join('\n\n'):'尚无复审结果；项目测试需自行运行。';
  $('record').textContent=s.record_path?'修复记录与备份：'+s.record_path:'';
  controls();
}
async function action(work) {
  if(busy) return;busy=true;controls();$('message').textContent='正在处理，请稍候…';
  try {await work();$('message').textContent='操作完成。';}
  catch(e){$('message').textContent=e.message;try{render(await api('state'));}catch(_) {}}
  finally{busy=false;controls();}
}
$('select').onclick=()=>action(async()=>{render(await api('select',{report:$('reports').value}));$('code').textContent='点击问题的“查看代码”。';});
$('validate').onclick=()=>action(async()=>render(await api('validate',{})));
$('generate').onclick=()=>action(async()=>render(await api('generate',{ids:Array.from(document.querySelectorAll('[data-issue]:checked')).map(e=>Number(e.dataset.issue))})));
$('apply').onclick=()=>{if(confirm('确认将预览中的补丁写入工作区？应用后将调用模型复审。')) action(async()=>{render(await api('apply',{ticket:state.proposal.ticket}));render(await api('verify',{}));});};
$('verify').onclick=()=>action(async()=>render(await api('verify',{})));
$('close').onclick=()=>action(async()=>{await api('close',{});$('phase').textContent='服务已关闭。';closed=true;state=null;});
action(async()=>render(await api('state')));
