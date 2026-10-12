/**
 * Node smoke tests for gai graph layout helpers (no DOM).
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

/* Linear history + side branch */
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
/* newest first */
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
var model = App.buildVisibleModel(commits, branches, tips, {
  collapseLinear: true,
  expanded: {},
  collapseMin: 3,
  hideLongEdges: true,
  longEdgeMin: 3,
});
assert(model.rows.length < commits.length, "linear collapse hides some rows");
var withFold = model.rows.filter(function (r) {
  return r.fold && r.fold.count > 0;
});
assert(withFold.length >= 1, "at least one linear fold arrow");
/* Fold host must still connect to a visible ancestor (parent rewrite). */
withFold.forEach(function (r) {
  assert(
    (r.parents && r.parents.length) || !r.fold.belowHash,
    "folded row keeps visible parent link via rewrite"
  );
  if (r.fold.belowHash) {
    assert(
      r.parents.indexOf(r.fold.belowHash) >= 0,
      "fold belowHash is a rewritten parent"
    );
  }
});

var rows = App.assignLanes(commits, colors);
assert(rows[0].color === colors.t1, "node color follows branch identity");
assert(Array.isArray(rows[0].parentEdgeColors), "parent edge colors present");

/* Re-lane after hide: visible geometry has contiguous prevAfter */
var vis = model.rows;
for (var i = 1; i < vis.length; i++) {
  assert(Array.isArray(vis[i].prevAfter), "prevAfter recomputed on visible rows");
}

/* Branch label color matches node color at tip */
var tipRow = vis.filter(function (r) {
  return r.commit.hash === "t1";
})[0];
assert(tipRow && tipRow.color === colors.t1, "tip row uses main branch color");

console.log("OK test_graph_layout.js");
