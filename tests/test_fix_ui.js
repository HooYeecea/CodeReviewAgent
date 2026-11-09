"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const nodes = new Map();
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.checked=false;this.disabled=false;this._text='';}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this._text='';this.children=items;}
}
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'src/gai/static/fix.html'),'utf8');
for(const match of html.matchAll(/<(\w+)[^>]* id="([^"]+)"/g))nodes.set(match[2],new Element(match[1]));
const all=()=>{const out=[];const walk=e=>{out.push(e);for(const c of e.children||[])walk(c);};for(const e of nodes.values())walk(e);return out;};
const calls=[];
let confirmed=false;
const finding=(id,status)=>({id,status,file:'a.txt',severity:'warning',line:1,issue:'<img src=x onerror=alert(1)>',suggestion:'fix',reason:'evidence',blocked:''});
let state={phase:'validated',report:{id:'abc'},note:'',reports:[],findings:[finding(1,'still_present'),finding(2,'uncertain')],proposal:null};
const context=vm.createContext({location:{hash:'#test-token'},confirm:()=>confirmed,
  document:{getElementById:id=>{assert(nodes.has(id),id);return nodes.get(id);},createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),
    querySelectorAll:selector=>all().filter(e=>selector.startsWith('[data-issue]')?e.dataset?.issue!==undefined&&(!selector.includes(':checked')||e.checked):['button','select','input'].includes(e.tag))},
  fetch:async(url,options)=>{calls.push({url,options});assert.equal(options.headers['X-Gai-Token'],'test-token');
    if(url==='/api/generate')state={...state,phase:'preview',proposal:{ticket:'ticket',files:[{file:'a.txt',issue_ids:[1],diff:'-old\n+new'}],unresolved:[]}};
    if(url==='/api/apply')state={...state,phase:'applied'};
    if(url==='/api/verify')state={...state,phase:'verified',verification:{checks:[]}};
    return {ok:true,json:async()=>state};}});
vm.runInContext(fs.readFileSync(path.join(root,'src/gai/static/fix.js'),'utf8'),context);
const tick=()=>new Promise(setImmediate);
(async()=>{
  await tick();
  const checks=all().filter(e=>e.dataset?.issue!==undefined);
  assert.equal(checks[0].disabled,false);assert.equal(checks[1].disabled,true);
  assert(nodes.get('findings').textContent.includes('<img src=x onerror=alert(1)>'));
  assert.equal(all().some(e=>e.tag==='img'),false);
  checks[0].checked=true;
  await nodes.get('generate').onclick();
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).ids,[1]);
  assert.equal(nodes.get('apply').disabled,false);
  nodes.get('apply').onclick();await tick();
  assert.equal(calls.some(c=>c.url==='/api/apply'),false);
  confirmed=true;nodes.get('apply').onclick();await tick();
  assert.equal(calls.at(-2).url,'/api/apply');assert.equal(calls.at(-1).url,'/api/verify');
  assert.equal(nodes.get('apply').disabled,true);
  await nodes.get('close').onclick();
  assert(all().filter(e=>e.tag==='button').every(e=>e.disabled));
})().catch(error=>{console.error(error);process.exitCode=1;});
