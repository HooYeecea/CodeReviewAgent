"use strict";
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
let state, tab = "personal", ticket = null, busy = false;
const labels = {profile:"当前配置档",current:"默认配置档",api_key:"API Key",base_url:"API 地址",model:"模型名称",timeout:"请求超时（秒）",max_diff_chars:"审查文本上限（字符）",ignore_patterns:"忽略规则（每行一项）",fail_on:"阻断提交的问题级别",require_complete:"要求完整审查",rules:"项目审查要求（每行一项）",review_rules:"审查要求"};
const reviewFields = ["max_diff_chars","fail_on","require_complete","ignore_patterns","rules"];
function display(value) { return value == null ? "（未设置）" : Array.isArray(value) ? (value.join("\n") || "（空）") : typeof value === "boolean" ? (value ? "是" : "否") : String(value); }
function message(text, error=false) { $("status").textContent=text; $("status").className=error?"error":""; }
async function api(path, data) {
  const response = await fetch("/api/"+path,{method:data===undefined?"GET":"POST",headers:{"X-Gai-Token":token,...(data===undefined?{}:{"Content-Type":"application/json"})},body:data===undefined?undefined:JSON.stringify(data),cache:"no-store"});
  const result = await response.json(); if(!response.ok) throw new Error(result.error || "操作失败"); return result;
}
function invalidate() { ticket=null; $("preview-panel").hidden=true; }
async function run(action) { if(busy) return; busy=true; document.body.inert=true; try { await action(); } catch(e) { message(e.message || "无法连接配置服务",true); } finally { busy=false; document.body.inert=false; } }
function row(body, cells) { const tr=document.createElement("tr"); cells.forEach(value=>{const td=document.createElement("td");if(value instanceof Node) td.append(value);else td.textContent=display(value);tr.append(td);}); body.append(tr); }
function fillEffective(id, values, before) { const body=$(id);body.replaceChildren();Object.entries(values).forEach(([key,item])=>row(body,before?[labels[key]||key,before[key]?.value,item.value,item.source]:[labels[key]||key,item.value,item.source])); }
function reviewForm(scope, values) {
  const container=$(scope+"-review");container.replaceChildren();
  reviewFields.forEach(key=>{
    const wrap=document.createElement("div");if(["rules","ignore_patterns"].includes(key))wrap.className="wide";
    const label=document.createElement("label");label.textContent=labels[key];
    let input;
    if(["fail_on","require_complete"].includes(key)) {
      input=document.createElement("select");const options=key==="fail_on"?[["none","不阻断"],["critical","严重问题"],["warning","警告及以上"],["info","所有问题"]]:[["false","允许不完整审查"],["true","必须完整"]];
      options.forEach(([value,text])=>{const o=document.createElement("option");o.value=value;o.textContent=text;input.append(o);});
    } else { input=document.createElement(["rules","ignore_patterns"].includes(key)?"textarea":"input");if(key==="max_diff_chars"){input.type="number";input.min="1";input.step="1";} }
    input.id=scope+"-"+key;const value=values[key]??state.review[key];input.value=Array.isArray(value)?value.join("\n"):String(value);
    if(scope==="project") {const check=document.createElement("label");check.className="check override";const toggle=document.createElement("input");toggle.type="checkbox";toggle.id="override-"+key;toggle.checked=Object.hasOwn(values,key);input.disabled=!toggle.checked;toggle.addEventListener("change",()=>{input.disabled=!toggle.checked;invalidate();});check.append(toggle,document.createTextNode("在当前项目覆盖此设置"));wrap.append(check);}
    label.append(input);wrap.append(label);container.append(wrap);
  });
}
function loadProfile() {
  const p=state.profiles[$("profile").value]||{};
  $("base_url").value=p.base_url||"https://api.openai.com/v1";$("model").value=p.model||"gpt-4o-mini";
  $("api_key").value="";$("clear-key").checked=false;$("api_key").disabled=false;
  $("key-hint").textContent=p.has_api_key?"文件中已有密钥。留空保留；输入新值则替换。":"文件中尚无密钥。可填写，也可保留环境变量中的密钥。";
  invalidate();
}
function envSelection() {
  const name=$("env-name").value, entry=state.environment.find(v=>v.name===name), isSecret=name.includes("API_KEY");
  $("env-value").type=isSecret?"password":"text";$("env-value").value=isSecret?"":(entry?.[$("env-scope").value]||"");
  $("env-value").placeholder=isSecret?"输入新密钥；已有密钥不回显":"输入要保存的值";
  // Registry scope is called 'user'; process scope matches the state key.
  $("env-value").disabled=$("env-action").value==="delete";invalidate();
}
function render(data) {
  state=data;invalidate();$("personal-path").textContent="保存位置："+data.personal_path;
  $("project-path").textContent=data.project_path?"保存位置："+data.project_path:"当前目录不是 Git 仓库，请从仓库目录启动 GUI。";
  $("profiles").replaceChildren();Object.keys(data.profiles).forEach(name=>{const o=document.createElement("option");o.value=name;$("profiles").append(o);});
  $("current").value=data.current;$("profile").value=data.current;$("timeout").value=data.timeout;loadProfile();
  reviewForm("personal",data.review);reviewForm("project",data.project);fillEffective("effective",data.effective);
  $("env-names").replaceChildren();$("env-table").replaceChildren();data.environment.forEach(entry=>{
    const option=document.createElement("option");option.value=entry.name;$("env-names").append(option);
    const button=document.createElement("button");button.textContent=entry.name;button.addEventListener("click",()=>{$("env-name").value=entry.name;envSelection();$("env-name").focus();});row($("env-table"),[button,entry.process,entry.user,entry.machine]);
  });
  $("env-scope").options[0].disabled=!data.user_environment_supported;if(!data.user_environment_supported)$("env-scope").value="process";
  envSelection();
}
function reviewValue(scope,key) { const raw=$(scope+"-"+key).value;if(key==="require_complete")return raw==="true";if(key==="max_diff_chars")return Number(raw);if(["rules","ignore_patterns"].includes(key))return raw.split("\n").map(x=>x.trim()).filter(Boolean);return raw; }
function payload() {
  if(tab==="environment")return {target:tab,name:$("env-name").value.trim(),scope:$("env-scope").value,value:$("env-action").value==="delete"?null:$("env-value").value};
  const fields={};
  if(tab==="project") {
    if(!state.project_path)throw new Error("请从 Git 仓库目录启动配置界面。");
    reviewFields.forEach(key=>{const value=$("override-"+key).checked?reviewValue(tab,key):null;if(JSON.stringify(value)!==JSON.stringify(state.project[key]??null))fields[key]=value;});
  } else {
    const p=state.profiles[$("profile").value]||{};
    ["base_url","model"].forEach(key=>{if($(key).value!==(p[key]||""))fields[key]=$(key).value;});
    if($("current").value!==state.current)fields.current=$("current").value;
    if(Number($("timeout").value)!==state.timeout)fields.timeout=Number($("timeout").value);
    if($("clear-key").checked)fields.api_key="";else if($("api_key").value)fields.api_key=$("api_key").value;
    reviewFields.forEach(key=>{const value=reviewValue(tab,key);if(JSON.stringify(value)!==JSON.stringify(state.review[key]))fields[key]=value;});
  }
  // An unchanged preview can still be used for connection testing.
  if(!Object.keys(fields).length){if(tab==="personal")fields.current=state.current;else throw new Error("没有需要保存的项目修改。");}
  return {target:tab,profile:$("profile").value,fields};
}
function showPreview(result) {
  ticket=result.ticket;$("destination").textContent="将保存到："+result.destination;$("preview-notes").textContent=result.notes.join("\n");
  $("changes").replaceChildren();result.changes.forEach(c=>row($("changes"),[labels[c.field]||c.field,c.before,c.removed?"删除此设置，使用回退值":c.after]));
  if(!result.changes.length)row($("changes"),["无值变更","可测试当前生效连接","保存仅规范化文件排版"]);
  $("fallback").hidden=!result.fallback;if(result.fallback)$("fallback").textContent="操作后的实际值："+display(result.fallback.value)+"\n来源："+result.fallback.source+(result.fallback.note?"\n"+result.fallback.note:"");
  fillEffective("after",result.after,result.before);$("preview-panel").hidden=false;$("preview-panel").scrollIntoView({behavior:"smooth",block:"start"});message("预览已生成。请核对修改、回退值和生效来源，再确认保存。");
}
document.querySelectorAll("[data-tab]").forEach(button=>button.addEventListener("click",()=>{tab=button.dataset.tab;document.querySelectorAll(".tab").forEach(section=>section.hidden=section.id!==tab);document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b===button));$("page-title").textContent={personal:"个人配置",project:"当前项目",environment:"环境变量"}[tab];invalidate();}));
document.addEventListener("input",event=>{if(event.target.matches("input,select,textarea"))invalidate();});
document.addEventListener("change",event=>{if(event.target.matches("input,select,textarea"))invalidate();});
$("profile").addEventListener("change",loadProfile);
$("clear-key").addEventListener("change",()=>{$("api_key").disabled=$("clear-key").checked;});
["env-name","env-scope","env-action"].forEach(id=>$(id).addEventListener("change",envSelection));
$("preview").addEventListener("click",()=>run(async()=>{invalidate();const draft=payload();showPreview(await api("preview",draft));}));
$("apply").addEventListener("click",()=>run(async()=>{const scope=tab==="environment"?$("env-scope").value:null;render(await api("apply",{ticket}));message(scope==="user"?"已保存用户环境变量。请重新打开终端或 IDE 后使用。":scope==="process"?"已应用到本 GUI 进程；关闭后失效。":"已保存配置。请查看下方的当前生效值与来源。");}));
$("test").addEventListener("click",()=>run(async()=>{message("正在测试预览中的当前生效连接…");message((await api("test",{ticket})).message);}));
$("cancel").addEventListener("click",()=>{invalidate();message("已取消预览，未保存。输入内容仍保留。");});
$("refresh").addEventListener("click",()=>run(async()=>{if(confirm("重新读取会丢弃尚未保存的表单修改，继续吗？")){render(await api("state"));message("已重新读取配置。");}}));
$("close").addEventListener("click",()=>run(async()=>{if(confirm("退出会丢弃未保存的修改，确定退出吗？")){message((await api("close",{})).message);invalidate();}}));
run(async()=>{if(!token)throw new Error("缺少会话信息，请使用 gai config --gui 启动后提供的完整地址。");render(await api("state"));});
