// Run the generated browser's real script against a minimal in-memory DOM.
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const page = fs.readFileSync(process.argv[2], "utf8");
const payload = page.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1];
const script = page.split("<script>")[1].split("</script>")[0];
class Element {
  constructor() { this.children = []; this.value = ""; this.textContent = ""; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
}
const ids = Object.fromEntries(["data","q","branch","severity","since","until","old","new","compare","detail","rows"]
  .map(id => [id, new Element()]));
ids.data.textContent = payload;
vm.runInNewContext(script, {document: {
  getElementById: id => ids[id],
  createElement: () => new Element()
}});
const data = JSON.parse(payload);
assert.equal(ids.rows.children.length, 2);
ids.severity.value = "critical";
ids.severity.oninput();
assert.equal(ids.rows.children.length, 1);
ids.rows.children[0].children.at(-1).children[0].onclick();
assert(ids.detail.textContent.includes("bug"));
assert(!ids.detail.textContent.includes('"snapshot"'));
ids.severity.value = "";
ids.q.value = data[1].title;
ids.q.oninput();
assert.equal(ids.rows.children.length, 1);
ids.q.value = "";
ids.since.value = "2999-01-01";
ids.since.oninput();
assert.equal(ids.rows.children.length, 0);
ids.old.value = data[0].id;
ids.new.value = data[1].id;
ids.compare.onclick();
assert(ids.detail.textContent.includes("待确认解决（1）"));
console.log("Review library interactions OK");
