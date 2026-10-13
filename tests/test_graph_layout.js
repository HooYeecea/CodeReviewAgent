/**
 * Node smoke tests for gai graph layout helpers (no DOM / no ECharts runtime).
 * Run: node tests/test_graph_layout.js
 */
var fs = require("fs");
var path = require("path");
var vm = require("vm");

var src = fs.readFileSync(
  path.join(__dirname, "..", "src", "gai", "static", "graph-app.js"),
  "utf8"
);
var sandbox = { window: {}, console: console };
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
var App = sandbox.window.GaiGraphApp;
if (!App) {
  console.error("GaiGraphApp missing");
  process.exit(1);
}

function assert(cond, msg) {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
}

var commits = [];
function add(hash, parents, subject) {
  commits.push({
    hash: hash,
    short: hash.slice(0, 7),
    parents: parents,
    author: "A",
    email: "a@t",
    date: "2026-01-01T00:00:00+08:00",
    subject: subject,
    body: "",
    decorations: "",
  });
}
add("t1", ["t2"], "tip main");
add("f1", ["t3"], "feature tip");
add("t2", ["t3"], "main mid");
add("t3", ["t4"], "shared");
add("t4", ["t5"], "old1");
add("t5", ["t6"], "old2");
add("t6", ["t7"], "old3");
add("t7", ["t8"], "old4");
add("t8", [], "root");

var branches = [
  { name: "main", tip: "t1", current: true },
  { name: "feature", tip: "f1", current: false },
];
commits[0].decorations = "HEAD -> main";
commits[1].decorations = "feature";

var colors = App.assignCommitColors(commits, branches);
assert(colors.t1 === colors.t2, "main first-parent chain shares color");
assert(colors.f1 !== colors.t1, "feature tip has distinct color from main tip");

var tips = { t1: [branches[0]], f1: [branches[1]] };
var modelExpanded = App.buildVisibleModel(commits, branches, tips, {
  collapseLinear: false,
  expanded: {},
  collapseMin: 3,
});
assert(modelExpanded.rows.length === commits.length, "expand keeps all rows");

var model = App.buildVisibleModel(commits, branches, tips, {
  collapseLinear: true,
  expanded: {},
  collapseMin: 3,
});
assert(model.rows.length < commits.length, "linear collapse hides some rows");

var g = App.toEchartsGraph(modelExpanded.rows, tips, { main: colors.t1, feature: colors.f1 }, false);
assert(g.nodes.length === modelExpanded.rows.length, "node count matches");
assert(g.links.length > 0, "has parent links");
assert(g.nodes[0].label && g.nodes[0].label.show === false, "labels hidden by default");
assert(Array.isArray(g.nodes[0].value) && g.nodes[0].value.length === 2, "cartesian [x,y]");
assert(g.nodes[1].value[1] > g.nodes[0].value[1], "rows increase downward in data");

var win = App.computeDataZoomWindow(g.nodes);
assert(win.yEnd - win.yStart <= 12.5, "default window shows about a dozen commits");
assert(win.yEnd - win.yStart >= 1, "window has positive span");

console.log("OK test_graph_layout.js");
