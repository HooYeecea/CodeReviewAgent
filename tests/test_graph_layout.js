/**
 * Node smoke tests for gai graph IDEA Log layout helpers.
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
assert(colors.f1 !== colors.t1, "feature tip distinct color");

var tips = { t1: [branches[0]], f1: [branches[1]] };
var expanded = App.buildVisibleModel(commits, branches, tips, {
  collapseLinear: false,
});
assert(expanded.rows.length === commits.length, "default expand keeps all rows");

var collapsed = App.buildVisibleModel(commits, branches, tips, {
  collapseLinear: true,
  collapseMin: 3,
  expanded: {},
});
assert(collapsed.rows.length < commits.length, "collapse hides linear middles");
assert(
  collapsed.rows.some(function (r) {
    return r.fold && r.fold.count > 0;
  }),
  "collapsed model has fold arrow host"
);

var tipRow = expanded.rows.filter(function (r) {
  return r.commit.hash === "t1";
})[0];
assert(tipRow && tipRow.color === colors.t1, "tip uses branch color");

assert(App.ROW_H === 22, "IDEA row height");
assert(App.NODE_W === 15, "IDEA node width");

// Merge: IDEA double-length DOWN docks with next-row UP.
var mergeCommits = [
  {
    hash: "m1",
    short: "m1",
    parents: ["t1", "f1"],
    author: "A",
    email: "a@t",
    date: "2026-01-02T00:00:00+08:00",
    subject: "Merge branch feature",
    body: "",
    decorations: "",
  },
].concat(commits);
var mergeModel = App.buildVisibleModel(mergeCommits, branches, tips, {
  collapseLinear: false,
});
var mergeRow = mergeModel.rows.filter(function (r) {
  return r.commit.hash === "m1";
})[0];
assert(mergeRow && mergeRow.parentCols.length === 2, "merge has two parent cols");
assert(
  mergeRow.parentCols[0] !== mergeRow.parentCols[1],
  "merge parents use distinct lanes"
);
var painted = App.drawCellSvg(mergeRow, { prevRow: null });
assert(painted.html.indexOf("overflow:visible") >= 0, "svg allows docking overflow");
var downY = App.ROW_H + App.ROW_H / 2;
assert(
  painted.html.indexOf('y2="' + downY + '"') >= 0 ||
    painted.html.indexOf('y2="' + downY.toFixed(1) + '"') >= 0 ||
    painted.html.indexOf("y2=\"" + String(downY) + "\"") >= 0,
  "cross-lane DOWN uses IDEA double-length y2=" + downY
);

var nextIdx = mergeModel.rows.indexOf(mergeRow) + 1;
var nextRow = mergeModel.rows[nextIdx];
var nextPaint = App.drawCellSvg(nextRow, { prevRow: mergeRow });
var upY = App.ROW_H / 2 - App.ROW_H;
assert(
  nextPaint.html.indexOf('y2="' + upY + '"') >= 0 ||
    nextPaint.html.indexOf("y2=\"" + String(upY) + "\"") >= 0,
  "next row paints matching UP half y2=" + upY
);

console.log("OK test_graph_layout.js");
