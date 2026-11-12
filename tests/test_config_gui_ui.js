"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const nodes = new Map();
class Element {
  constructor() { this.children=[];this.events={};this.value="";this._text="";this.options=[{},{}];this.classList={toggle(){}}; }
  set id(value){this._id=value;nodes.set(value,this);}
  get id(){return this._id;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent??String(x)).join("");}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this._text="";this.children=items;}
  addEventListener(name,action){this.events[name]=action;}
  scrollIntoView(){}
  focus(){}
}
const root=path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"src/gai/static/config.html"),"utf8");
for(const match of html.matchAll(/id="([^"]+)"/g)){const node=new Element();node.id=match[1];}
nodes.get("env-name").value="GAI_MODEL";nodes.get("env-action").value="set";nodes.get("env-scope").value="user";
const data={personal_path:"config.toml",project_path:"",profiles:{"0":{}},current:"0",timeout:5,
 review:{max_diff_chars:1000,ignore_patterns:[],fail_on:"none",require_complete:false,rules:[]},
 project:{},environment:[],effective:{},user_environment_supported:true};
const context=vm.createContext({Node:Element,location:{hash:"#dummy-token"},
 document:{body:{},getElementById(id){assert(nodes.has(id),id);return nodes.get(id);},
   createElement(){return new Element();},createTextNode(text){return {textContent:text};},
   querySelectorAll(){return [];},addEventListener(){}},
 fetch:async()=>({ok:true,json:async()=>data}),confirm:()=>true});
vm.runInContext(fs.readFileSync(path.join(root,"src/gai/static/config.js"),"utf8"),context);
(async()=>{
 await new Promise(setImmediate);
 vm.runInContext("tab='environment'",context);
 const queue=(name,value)=>{nodes.get("env-name").value=name;nodes.get("env-value").value=value;nodes.get("env-add").events.click();};
 queue("GAI_TIMEOUT","12");queue("GAI_API_KEY","SECRET_DRAFT");
 const draft=vm.runInContext("payload()",context);
 assert.equal(draft.changes.GAI_TIMEOUT,"12");assert.equal(draft.changes.GAI_API_KEY,"SECRET_DRAFT");
 assert.equal(nodes.get("env-scope").disabled,true);
 assert(!nodes.get("env-draft").textContent.includes("SECRET_DRAFT"));
 assert.equal(nodes.get("env-value").value,"");
 nodes.get("env-draft").children[0].children[2].children[0].events.click();
 assert.equal(vm.runInContext("payload().changes.GAI_TIMEOUT",context),undefined);
 nodes.get("env-clear").events.click();
 assert.equal(nodes.get("env-scope").disabled,false);
 assert.equal(nodes.get("env-draft").children.length,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
