/**
 * gai graph — IDEA Log style commit table with metro lanes.
 * Default: all commits expanded; hover summary; click detail drawer.
 */
(function (global) {
  "use strict";

  var COLORS = [
    "#589df6",
    "#e68545",
    "#f5c542",
    "#62b543",
    "#b57edc",
    "#3dbeb8",
    "#e75a8a",
    "#8a9ba8",
    "#c27a4b",
    "#6c8cd5",
  ];

  // Match IntelliJ PaintParameters (ROW_HEIGHT=22, WIDTH_NODE=15, CIRCLE_RADIUS=4).
  var ROW_H = 22;
  var NODE_W = 15;
  var LINE_W = 1.5;
  var CIRCLE_R = 4;
  var ARROW_LEN = 0.3;
  var ARROW_COS2 = 0.7;
  var COLLAPSE_MIN = 3;

  function colorOf(i) {
    return COLORS[((i % COLORS.length) + COLORS.length) % COLORS.length];
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      var pad = function (n) {
        return n < 10 ? "0" + n : "" + n;
      };
      return (
        d.getFullYear() +
        "-" +
        pad(d.getMonth() + 1) +
        "-" +
        pad(d.getDate()) +
        " " +
        pad(d.getHours()) +
        ":" +
        pad(d.getMinutes())
      );
    } catch (e) {
      return iso;
    }
  }

  function branchColorMap(branches) {
    var map = {};
    (branches || []).forEach(function (b, i) {
      map[b.name] = colorOf(i);
    });
    return map;
  }

  function tipMap(branches) {
    var tips = {};
    (branches || []).forEach(function (b) {
      if (!b.tip) return;
      if (!tips[b.tip]) tips[b.tip] = [];
      tips[b.tip].push(b);
    });
    return tips;
  }

  function indexByHash(commits) {
    var map = {};
    (commits || []).forEach(function (c) {
      map[c.hash] = c;
    });
    return map;
  }

  function assignCommitColors(commits, branches) {
    var bmap = branchColorMap(branches);
    var byH = indexByHash(commits);
    var color = {};
    var ordered = (branches || []).slice().sort(function (a, b) {
      return (b.current ? 1 : 0) - (a.current ? 1 : 0);
    });
    ordered.forEach(function (b) {
      var col = bmap[b.name] || colorOf(0);
      var stack = [b.tip];
      var seen = {};
      while (stack.length) {
        var h = stack.pop();
        if (!h || seen[h]) continue;
        seen[h] = true;
        if (!color[h]) color[h] = col;
        var c = byH[h];
        if (!c) continue;
        (c.parents || []).forEach(function (p) {
          stack.push(p);
        });
      }
    });
    (commits || []).forEach(function (c, i) {
      if (!color[c.hash]) color[c.hash] = colorOf(i);
    });
    return color;
  }

  function refsFor(commit, tips) {
    var refs = [];
    var seen = {};
    function add(name, kind) {
      var key = kind + ":" + name;
      if (seen[key]) return;
      seen[key] = true;
      refs.push({ name: name, kind: kind });
    }
    (tips[commit.hash] || []).forEach(function (b) {
      add(b.name, "branch");
      if (b.current) add("HEAD", "head");
    });
    String(commit.decorations || "")
      .split(",")
      .forEach(function (part) {
        var token = part.trim();
        if (!token) return;
        if (token.indexOf("tag: ") === 0) {
          add(token.slice(5), "tag");
          return;
        }
        if (token.indexOf(" -> ") >= 0) {
          var right = token.split(" -> ")[1].trim();
          if (right) add(right, "branch");
          if (token.indexOf("HEAD") === 0) add("HEAD", "head");
          return;
        }
        if (token === "HEAD") add("HEAD", "head");
        else if (token.indexOf("origin/") !== 0 && token.indexOf("tag:") !== 0) add(token, "branch");
      });
    return refs;
  }

  function filterCommits(commits, branches, sel) {
    var chosen = (branches || []).filter(function (b) {
      return sel[b.name];
    });
    if (!chosen.length) return [];
    if (chosen.length === (branches || []).length) return commits.slice();
    var map = indexByHash(commits);
    var keep = {};
    var stack = chosen.map(function (b) {
      return b.tip;
    });
    while (stack.length) {
      var h = stack.pop();
      if (!h || keep[h]) continue;
      keep[h] = true;
      var c = map[h];
      if (!c) continue;
      (c.parents || []).forEach(function (p) {
        stack.push(p);
      });
    }
    return (commits || []).filter(function (c) {
      return keep[c.hash];
    });
  }

  function buildChildren(commits) {
    var children = {};
    commits.forEach(function (c) {
      (c.parents || []).forEach(function (p) {
        if (!children[p]) children[p] = [];
        children[p].push(c.hash);
      });
    });
    return children;
  }

  function isOrdinary(commit, children, tips) {
    if ((tips[commit.hash] || []).length) return false;
    if ((commit.parents || []).length !== 1) return false;
    var kids = children[commit.hash] || [];
    if (kids.length !== 1) return false;
    var deco = String(commit.decorations || "").trim();
    if (deco && deco !== "HEAD") return false;
    return true;
  }

  function planLinearFolds(commits, children, tips, collapseMin, expanded) {
    var min = Math.max(1, collapseMin || COLLAPSE_MIN);
    var hidden = {};
    var foldsByAbove = {};
    var i = 0;
    while (i < commits.length) {
      if (!isOrdinary(commits[i], children, tips)) {
        i++;
        continue;
      }
      var start = i;
      while (i < commits.length && isOrdinary(commits[i], children, tips)) i++;
      var run = i - start;
      if (run < min) continue;
      var hashes = [];
      for (var k = start; k < i; k++) hashes.push(commits[k].hash);
      var sid = hashes[0] + ".." + hashes[hashes.length - 1];
      if (expanded[sid]) continue;
      hashes.forEach(function (h) {
        hidden[h] = true;
      });
      var aboveHash = start > 0 ? commits[start - 1].hash : null;
      if (aboveHash) {
        foldsByAbove[aboveHash] = {
          id: sid,
          count: run,
          hashes: hashes,
          belowHash: i < commits.length ? commits[i].hash : null,
        };
      } else {
        delete hidden[hashes[0]];
        foldsByAbove[hashes[0]] = {
          id: sid,
          count: run - 1,
          hashes: hashes.slice(1),
          belowHash: i < commits.length ? commits[i].hash : null,
        };
        for (var k3 = 1; k3 < hashes.length; k3++) hidden[hashes[k3]] = true;
      }
    }
    return { hidden: hidden, foldsByAbove: foldsByAbove };
  }

  function resolveVisibleAncestor(startHash, hidden, visibleSet, byAll) {
    var h = startHash;
    var guard = 0;
    while (h && guard++ < 10000) {
      if (visibleSet[h] && !hidden[h]) return h;
      var c = byAll[h];
      if (!c || !(c.parents || []).length) return null;
      h = c.parents[0];
    }
    return null;
  }

  function rewriteVisibleCommits(commits, hidden) {
    var byAll = indexByHash(commits);
    var visibleSet = {};
    commits.forEach(function (c) {
      if (!hidden[c.hash]) visibleSet[c.hash] = true;
    });
    return commits
      .filter(function (c) {
        return !hidden[c.hash];
      })
      .map(function (c) {
        var parents = [];
        var seen = {};
        (c.parents || []).forEach(function (p) {
          var v = resolveVisibleAncestor(p, hidden, visibleSet, byAll);
          if (v && !seen[v]) {
            seen[v] = true;
            parents.push(v);
          }
        });
        return {
          hash: c.hash,
          short: c.short,
          parents: parents,
          author: c.author,
          email: c.email,
          date: c.date,
          subject: c.subject,
          body: c.body,
          decorations: c.decorations,
        };
      });
  }

  function assignLanes(commits, commitColors) {
    commitColors = commitColors || {};
    var map = indexByHash(commits);
    var columns = [];
    var laneColors = [];
    var rows = [];
    var prevAfter = [];
    var prevColors = [];

    commits.forEach(function (c) {
      var arrivedFromAbove = columns.indexOf(c.hash) >= 0;
      var col = columns.indexOf(c.hash);
      var nodeColor = commitColors[c.hash] || colorOf(col < 0 ? columns.length : col);
      if (col < 0) {
        col = columns.indexOf(null);
        if (col < 0) {
          col = columns.length;
          columns.push(c.hash);
          laneColors.push(nodeColor);
        } else {
          columns[col] = c.hash;
          laneColors[col] = nodeColor;
        }
      } else if (!arrivedFromAbove) {
        laneColors[col] = nodeColor;
      } else if (!laneColors[col]) {
        laneColors[col] = nodeColor;
      }

      var before = columns.slice();
      var colorsBefore = laneColors.slice();
      var next = columns.slice();
      var colorsNext = laneColors.slice();
      next[col] = null;

      var parents = (c.parents || []).filter(function (p) {
        return !!map[p];
      });
      var placedFirst = false;
      var parentCols = [];
      var parentEdgeColors = [];

      parents.forEach(function (p) {
        var existing = next.indexOf(p);
        var pColor = commitColors[p] || laneColors[col] || nodeColor;
        if (existing >= 0) {
          parentCols.push(existing);
          parentEdgeColors.push(colorsNext[existing] || pColor);
          return;
        }
        if (!placedFirst) {
          next[col] = p;
          colorsNext[col] = colorsBefore[col] || pColor;
          parentCols.push(col);
          parentEdgeColors.push(colorsNext[col]);
          placedFirst = true;
        } else {
          var free = next.indexOf(null);
          var slot;
          if (free < 0) {
            slot = next.length;
            next.push(p);
            colorsNext.push(pColor);
          } else {
            slot = free;
            next[free] = p;
            colorsNext[free] = pColor;
          }
          parentCols.push(slot);
          parentEdgeColors.push(colorsNext[slot]);
        }
      });

      while (next.length && next[next.length - 1] === null) {
        next.pop();
        colorsNext.pop();
      }

      rows.push({
        commit: c,
        col: col,
        color: colorsBefore[col] || nodeColor,
        before: before,
        after: next.slice(),
        colorsBefore: colorsBefore.slice(),
        colorsAfter: colorsNext.slice(),
        prevAfter: prevAfter.slice(),
        prevColors: prevColors.slice(),
        arrivedFromAbove: arrivedFromAbove,
        parents: parents,
        parentCols: parentCols,
        parentEdgeColors: parentEdgeColors,
        fold: null,
      });
      prevAfter = next.slice();
      prevColors = colorsNext.slice();
      columns = next;
      laneColors = colorsNext;
    });
    return rows;
  }

  function buildVisibleModel(commits, branches, tips, opts) {
    opts = opts || {};
    var children = buildChildren(commits);
    var commitColors = assignCommitColors(commits, branches);
    var collapseOn = opts.collapseLinear === true;
    var expanded = opts.expanded || {};
    var hidden = {};
    var foldsByAbove = {};

    if (collapseOn) {
      var plan = planLinearFolds(
        commits,
        children,
        tips,
        opts.collapseMin || COLLAPSE_MIN,
        expanded
      );
      hidden = plan.hidden;
      foldsByAbove = plan.foldsByAbove;
    }

    var visibleCommits = rewriteVisibleCommits(commits, hidden);
    var rows = assignLanes(visibleCommits, commitColors);
    rows.forEach(function (r) {
      var fold = foldsByAbove[r.commit.hash];
      if (fold && fold.count > 0) {
        r.fold = {
          id: fold.id,
          count: fold.count,
          hashes: fold.hashes,
          belowHash: fold.belowHash,
          col: r.col,
          color: r.color,
        };
      }
    });
    return { rows: rows, commitColors: commitColors, hidden: hidden };
  }

  function laneX(col) {
    return NODE_W * col + NODE_W / 2;
  }

  function rotate(x1, y1, x2, y2, cos, sin, len) {
    var dx = x2 - x1;
    var dy = y2 - y1;
    var d = Math.sqrt(dx * dx + dy * dy) || 1;
    var ux = (dx / d) * len;
    var uy = (dy / d) * len;
    return {
      x: x2 - ux * cos + uy * sin,
      y: y2 - uy * cos - ux * sin,
    };
  }

  function paintArrowHead(parts, x1, y1, tipX, tipY, color) {
    var len = ARROW_LEN * ROW_H;
    var cos = Math.sqrt(ARROW_COS2);
    var sin = Math.sqrt(1 - ARROW_COS2);
    var a = rotate(x1, y1, tipX, tipY, cos, sin, len);
    var b = rotate(x1, y1, tipX, tipY, cos, -sin, len);
    parts.push(
      '<line x1="' + tipX + '" y1="' + tipY + '" x2="' + a.x + '" y2="' + a.y +
      '" stroke="' + color + '" stroke-width="' + LINE_W + '" stroke-linecap="round"/>'
    );
    parts.push(
      '<line x1="' + tipX + '" y1="' + tipY + '" x2="' + b.x + '" y2="' + b.y +
      '" stroke="' + color + '" stroke-width="' + LINE_W + '" stroke-linecap="round"/>'
    );
  }

  function strokeLine(parts, x1, y1, x2, y2, color, dashed) {
    parts.push(
      '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
      '" stroke="' + color + '" stroke-width="' + LINE_W +
      '" stroke-linecap="round" stroke-linejoin="round"' +
      (dashed ? ' stroke-dasharray="2.5 2.5"' : "") + "/>"
    );
  }

  /**
   * IDEA SimpleGraphCellPainter: non-vertical DOWN edges are painted to
   * (otherLane, rowHeight + rowCenter) so they dock with the matching UP edge
   * in the next row (drawn to y = rowCenter - rowHeight).
   */
  function drawCellSvg(row, opts) {
    opts = opts || {};
    var after = row.after || [];
    var prevAfter = row.prevAfter || [];
    var colorsBefore = row.colorsBefore || [];
    var colorsAfter = row.colorsAfter || [];
    var prevColors = row.prevColors || [];
    var prevRow = opts.prevRow || null;
    var parentCols = row.parentCols || [];
    var edgeColors = row.parentEdgeColors || [];
    var laneCount = Math.max(
      after.length,
      prevAfter.length,
      parentCols.reduce(function (m, c) {
        return Math.max(m, c + 1);
      }, 0),
      row.col + 1,
      1
    );
    if (prevRow) {
      (prevRow.parentCols || []).forEach(function (pc) {
        laneCount = Math.max(laneCount, pc + 1, prevRow.col + 1);
      });
    }
    var w = Math.max(NODE_W * laneCount + NODE_W, NODE_W * 2);
    var h = ROW_H;
    var mid = h / 2;
    var parts = [];
    parts.push(
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h +
      '" viewBox="0 0 ' + w + " " + h + '" class="graph-svg" style="overflow:visible">'
    );

    var hasFoldArrow = !!(row.fold && row.fold.count);
    var crossDown = {};
    parentCols.forEach(function (pc) {
      if (pc !== row.col) crossDown[pc] = true;
    });
    var incomingCross = {};
    if (prevRow && !(prevRow.fold && prevRow.fold.count)) {
      (prevRow.parentCols || []).forEach(function (pc, idx) {
        if (pc === prevRow.col) return;
        incomingCross[pc] = {
          fromCol: prevRow.col,
          color:
            (prevRow.parentEdgeColors && prevRow.parentEdgeColors[idx]) ||
            prevRow.color ||
            colorOf(pc),
        };
      });
    }

    // Passthrough / side lanes (not the node column).
    for (var j = 0; j < laneCount; j++) {
      if (j === row.col) continue;
      var top = prevAfter[j] != null;
      var bot = after[j] != null;
      if (!top && !bot && !incomingCross[j] && !crossDown[j]) continue;
      var x = laneX(j);
      var c = (top ? prevColors[j] : colorsAfter[j]) || colorsBefore[j] || colorOf(j);

      if (incomingCross[j]) {
        // Matching UP half of IDEA double-length diagonal from previous row.
        strokeLine(
          parts,
          x,
          mid,
          laneX(incomingCross[j].fromCol),
          mid - h,
          incomingCross[j].color,
          false
        );
        if (bot) strokeLine(parts, x, mid, x, h, incomingCross[j].color || c, false);
        continue;
      }

      if (crossDown[j]) {
        // DOWN half is drawn from the node; do not orphan a mid→bottom stub.
        continue;
      }

      if (top && bot) strokeLine(parts, x, 0, x, h, c, false);
      else if (top) strokeLine(parts, x, 0, x, mid, c, false);
      else if (bot) strokeLine(parts, x, mid, x, h, c, false);
    }

    var cx = laneX(row.col);
    var main = row.color || colorsBefore[row.col] || colorOf(row.col);

    // Vertical UP into the node (unless a cross diagonal already arrives here).
    if (row.arrivedFromAbove && !incomingCross[row.col]) {
      strokeLine(parts, cx, 0, cx, mid, main, false);
    }
    if (incomingCross[row.col]) {
      strokeLine(
        parts,
        cx,
        mid,
        laneX(incomingCross[row.col].fromCol),
        mid - h,
        incomingCross[row.col].color,
        false
      );
    }

    if (hasFoldArrow) {
      var fc = (row.fold && row.fold.color) || main;
      var yTip = h - (CIRCLE_R / 2 + 1);
      strokeLine(parts, cx, mid, cx, yTip, fc, true);
      paintArrowHead(parts, cx, mid, cx, yTip, fc);
      parts.push(
        '<rect class="fold-hit" data-fold="' + escapeHtml(row.fold.id) +
        '" data-count="' + row.fold.count +
        '" x="' + (cx - 7) + '" y="' + (mid + 2) +
        '" width="14" height="' + (h - mid - 2) +
        '" fill="transparent" style="cursor:pointer"/>'
      );
    } else {
      parentCols.forEach(function (pc, idx) {
        var px = laneX(pc);
        var c2 = edgeColors[idx] || colorsAfter[pc] || main;
        if (pc === row.col) {
          strokeLine(parts, cx, mid, cx, h, c2, false);
        } else {
          // IDEA: paint non-vertical DOWN edges twice the size to dock with UP.
          strokeLine(parts, cx, mid, px, h + mid, c2, false);
        }
      });
    }

    parts.push(
      '<circle cx="' + cx + '" cy="' + mid + '" r="' + CIRCLE_R +
      '" fill="' + main + '" stroke="' + main + '"/>'
    );
    if (opts.selected) {
      parts.push(
        '<circle cx="' + cx + '" cy="' + mid + '" r="' + (CIRCLE_R + 2.5) +
        '" fill="none" stroke="' + main + '" stroke-width="' + (LINE_W + 1) +
        '" opacity="0.55"/>'
      );
    }
    parts.push("</svg>");
    return { html: parts.join(""), width: w };
  }

  function createApp(options) {
    var prefLang = options.prefLang || "gai-ui-lang";
    var prefTheme = options.prefTheme || "gai-ui-theme";
    var selected = {};
    var expanded = {};
    var activeHash = null;
    var byHash = {};
    var data = options.data || {};
    var collapseLinear = false;

    function bootData() {
      if (global.GAI_GRAPH_DATA) return global.GAI_GRAPH_DATA;
      try {
        return JSON.parse(document.getElementById("gai-graph-bootstrap").textContent);
      } catch (e) {
        return { commits: [], branches: [], i18n: {} };
      }
    }

    data = bootData();

    function I18N() {
      var lang = document.documentElement.getAttribute("data-lang") || "en";
      return (data.i18n && data.i18n[lang]) || (data.i18n && data.i18n.en) || {};
    }

    function applyI18n() {
      var dict = I18N();
      document.querySelectorAll("[data-i]").forEach(function (el) {
        var key = el.getAttribute("data-i");
        if (dict[key]) el.textContent = dict[key];
      });
    }

    function showToast(msg) {
      var el = document.getElementById("toast");
      el.textContent = msg;
      el.classList.add("show");
      clearTimeout(showToast._t);
      showToast._t = setTimeout(function () {
        el.classList.remove("show");
      }, 3200);
    }

    function updateRepoMeta() {
      document.getElementById("repo-name").textContent = data.repoName || "—";
      var dict = I18N();
      var remoteEl = document.getElementById("repo-remote");
      if (data.remoteUrl) {
        remoteEl.textContent =
          (dict.remote || "Remote") +
          " · " +
          (data.remoteName ? data.remoteName + ": " : "") +
          data.remoteUrl;
      } else {
        remoteEl.textContent = (dict.remote || "Remote") + " · " + (dict.no_remote || "(none)");
      }
    }

    function buildFilterUI(branches) {
      var box = document.getElementById("branch-checks");
      var bmap = branchColorMap(branches);
      box.innerHTML = "";
      (branches || []).forEach(function (b) {
        if (selected[b.name] === undefined) selected[b.name] = true;
        var lab = document.createElement("label");
        if (b.current) lab.className = "current";
        lab.innerHTML =
          '<input type="checkbox" data-branch="' + escapeHtml(b.name) + '"' +
          (selected[b.name] ? " checked" : "") + " />" +
          '<span class="dot" style="background:' + (bmap[b.name] || colorOf(0)) + '"></span>' +
          "<span>" + escapeHtml(b.name) + (b.current ? " ★" : "") + "</span>";
        box.appendChild(lab);
      });
      box.querySelectorAll("input[type=checkbox]").forEach(function (inp) {
        inp.addEventListener("change", function () {
          selected[inp.getAttribute("data-branch")] = inp.checked;
          paint();
        });
      });
    }

    function setSelection(mode) {
      var branches = data.branches || [];
      branches.forEach(function (b) {
        if (mode === "all") selected[b.name] = true;
        else if (mode === "none") selected[b.name] = false;
        else selected[b.name] = !!b.current;
      });
      if (
        mode === "current" &&
        !branches.some(function (b) {
          return selected[b.name];
        }) &&
        branches[0]
      ) {
        selected[branches[0].name] = true;
      }
      buildFilterUI(branches);
      paint();
    }

    function showTooltip(html, ev) {
      var tip = document.getElementById("tooltip");
      tip.innerHTML = html;
      tip.style.display = "block";
      moveTooltip(ev);
    }

    function moveTooltip(ev) {
      var tip = document.getElementById("tooltip");
      if (tip.style.display === "none") return;
      var x = ev.clientX + 14;
      var y = ev.clientY + 14;
      var rect = tip.getBoundingClientRect();
      if (x + rect.width > window.innerWidth - 8) x = ev.clientX - rect.width - 10;
      if (y + rect.height > window.innerHeight - 8) y = ev.clientY - rect.height - 10;
      tip.style.left = x + "px";
      tip.style.top = y + "px";
    }

    function hideTooltip() {
      document.getElementById("tooltip").style.display = "none";
    }

    function commitTooltipHtml(commit) {
      var refs = refsFor(commit, tipMap(data.branches))
        .map(function (r) {
          return r.name;
        })
        .join(", ");
      return (
        '<div class="t-sub">' + escapeHtml(commit.subject || "") + "</div>" +
        '<div class="t-meta">' + escapeHtml(commit.short || "") + " · " +
        escapeHtml(commit.author || "") + "</div>" +
        '<div class="t-meta">' + escapeHtml(formatDate(commit.date)) + "</div>" +
        (refs ? '<div class="t-meta">' + escapeHtml(refs) + "</div>" : "")
      );
    }

    function openDetail(hash) {
      var c = byHash[hash];
      if (!c) return;
      activeHash = hash;
      var dict = I18N();
      document.getElementById("layout").classList.remove("no-detail");
      var tips = tipMap(data.branches);
      var refs = refsFor(c, tips);
      var bmap = branchColorMap(data.branches);
      var ccolors = assignCommitColors(data.commits || [], data.branches || []);
      var refHtml = refs.length
        ? refs
            .map(function (r) {
              var col =
                r.kind === "tag"
                  ? "#9b6bdf"
                  : r.kind === "head"
                    ? "#6e6e6e"
                    : bmap[r.name] || ccolors[c.hash] || colorOf(0);
              return (
                '<span class="ref-pill' + (r.kind === "head" ? " head" : "") +
                '" style="background:' + col + '">' + escapeHtml(r.name) + "</span>"
              );
            })
            .join(" ")
        : escapeHtml(dict.detail_none || "(none)");
      var parents = c.parents || [];
      var parentHtml = parents.length
        ? parents
            .map(function (p) {
              var pc = byHash[p];
              var label = pc && pc.short ? pc.short : p.slice(0, 7);
              var sub = pc ? " — " + (pc.subject || "") : "";
              return (
                '<span class="parent-link" data-parent="' + escapeHtml(p) + '">' +
                escapeHtml(label) + escapeHtml(sub) + "</span>"
              );
            })
            .join("")
        : escapeHtml(dict.detail_none || "(none)");
      var body = ((c.subject || "") + (c.body ? "\n\n" + c.body : "")).trim();
      document.getElementById("drawer-body").innerHTML =
        '<div class="k">' + escapeHtml(dict.detail_hash || "Commit") + "</div>" +
        '<div class="v mono">' + escapeHtml(c.hash) + "</div>" +
        '<div class="k">' + escapeHtml(dict.detail_author || "Author") + "</div>" +
        '<div class="v">' + escapeHtml(c.author || "") +
        (c.email ? " &lt;" + escapeHtml(c.email) + "&gt;" : "") + "</div>" +
        '<div class="k">' + escapeHtml(dict.detail_date || "Date") + "</div>" +
        '<div class="v">' + escapeHtml(formatDate(c.date) || c.date || "") + "</div>" +
        '<div class="k">' + escapeHtml(dict.detail_refs || "Refs") + "</div>" +
        '<div class="v">' + refHtml + "</div>" +
        '<div class="k">' + escapeHtml(dict.detail_parents || "Parents") + "</div>" +
        '<div class="v">' + parentHtml + "</div>" +
        '<div class="k">' + escapeHtml(dict.detail_body || "Message") + "</div>" +
        '<div class="v"><pre class="body">' +
        escapeHtml(body || dict.detail_none || "") + "</pre></div>";
      document.querySelectorAll("#drawer-body .parent-link").forEach(function (el) {
        el.addEventListener("click", function () {
          var ph = el.getAttribute("data-parent");
          openDetail(ph);
          paint();
          var row = document.querySelector('tr.commit-row[data-hash="' + ph + '"]');
          if (row) row.scrollIntoView({ block: "center", behavior: "smooth" });
        });
      });
      document.querySelectorAll("tr.commit-row").forEach(function (tr) {
        tr.classList.toggle("active", tr.getAttribute("data-hash") === hash);
      });
    }

    function closeDetail() {
      activeHash = null;
      document.getElementById("layout").classList.add("no-detail");
      document.querySelectorAll("tr.commit-row").forEach(function (tr) {
        tr.classList.remove("active");
      });
    }

    function paint() {
      document.getElementById("branch").textContent = data.branch || "—";
      document.getElementById("generated").textContent = data.generated || "";
      updateRepoMeta();

      var commits = filterCommits(data.commits || [], data.branches || [], selected);
      byHash = {};
      (data.commits || []).forEach(function (c) {
        byHash[c.hash] = c;
      });

      var empty = document.getElementById("empty");
      var table = document.getElementById("graph-table");
      var tbody = document.getElementById("graph-body");
      tbody.innerHTML = "";
      var dict = I18N();

      if (!(data.commits || []).length) {
        empty.hidden = false;
        table.hidden = true;
        document.getElementById("empty-text").textContent = dict.empty || "Empty";
        return;
      }
      if (!commits.length) {
        empty.hidden = false;
        table.hidden = true;
        document.getElementById("empty-text").textContent =
          dict.empty_filter || dict.empty || "Empty";
        return;
      }
      empty.hidden = true;
      table.hidden = false;

      var tips = tipMap(data.branches);
      var model = buildVisibleModel(commits, data.branches || [], tips, {
        collapseLinear: collapseLinear,
        expanded: expanded,
        collapseMin: data.collapseMin || COLLAPSE_MIN,
      });
      var visible = model.rows;
      var bmap = branchColorMap(data.branches);
      var maxGraphW = NODE_W * 2;

      visible.forEach(function (row, idx) {
        var c = row.commit;
        var tr = document.createElement("tr");
        tr.className = "commit-row" + (activeHash === c.hash ? " active" : "");
        tr.setAttribute("data-hash", c.hash);
        var painted = drawCellSvg(row, {
          selected: activeHash === c.hash,
          prevRow: idx > 0 ? visible[idx - 1] : null,
        });
        if (painted.width > maxGraphW) maxGraphW = painted.width;

        var refs = refsFor(c, tips);
        var pills = refs
          .map(function (r) {
            var col =
              r.kind === "tag"
                ? "#9b6bdf"
                : r.kind === "head"
                  ? "#6e6e6e"
                  : bmap[r.name] || row.color || colorOf(0);
            return (
              '<span class="ref-pill' + (r.kind === "head" ? " head" : "") +
              '" style="background:' + col + '">' + escapeHtml(r.name) + "</span>"
            );
          })
          .join("");

        var isMerge =
          (c.parents && c.parents.length > 1) ||
          /^\s*merge\b/i.test(c.subject || "");
        tr.innerHTML =
          '<td class="graph-cell">' + painted.html + "</td>" +
          '<td class="msg-cell"><div class="msg">' + pills +
          '<span class="subject' + (isMerge ? " merge" : "") + '">' +
          escapeHtml(c.subject || "") + "</span></div></td>" +
          '<td class="author">' + escapeHtml(c.author || "") + "</td>" +
          '<td class="date">' + escapeHtml(formatDate(c.date)) + "</td>" +
          '<td class="hash">' + escapeHtml(c.short || "") + "</td>";

        tr.addEventListener("mouseenter", function (ev) {
          showTooltip(commitTooltipHtml(c), ev);
        });
        tr.addEventListener("mousemove", moveTooltip);
        tr.addEventListener("mouseleave", hideTooltip);
        tr.addEventListener("click", function (ev) {
          if (ev.target && ev.target.classList && ev.target.classList.contains("fold-hit")) {
            return;
          }
          openDetail(c.hash);
          paint();
        });

        var hit = tr.querySelector(".fold-hit");
        if (hit) {
          hit.addEventListener("mouseenter", function (ev) {
            ev.stopPropagation();
            var n = hit.getAttribute("data-count");
            var msg = (dict.expand || "Expand {n} commits").replace("{n}", n);
            showTooltip(
              '<div class="t-sub">' + escapeHtml(msg) + "</div>" +
              '<div class="t-meta">' + escapeHtml(dict.collapse_hint || "") + "</div>",
              ev
            );
          });
          hit.addEventListener("mousemove", function (ev) {
            ev.stopPropagation();
            moveTooltip(ev);
          });
          hit.addEventListener("mouseleave", function (ev) {
            ev.stopPropagation();
            hideTooltip();
          });
          hit.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            expanded[hit.getAttribute("data-fold")] = true;
            hideTooltip();
            paint();
          });
        }

        tbody.appendChild(tr);
      });

      document.querySelectorAll("th.graph-h, col.graph-col").forEach(function (el) {
        el.style.width = maxGraphW + 10 + "px";
      });

      if (activeHash && byHash[activeHash]) {
        document.querySelectorAll("tr.commit-row").forEach(function (tr) {
          tr.classList.toggle("active", tr.getAttribute("data-hash") === activeHash);
        });
      } else if (activeHash) {
        closeDetail();
      }
    }

    function render(d) {
      data = d || data;
      (data.branches || []).forEach(function (b) {
        if (selected[b.name] === undefined) selected[b.name] = true;
      });
      buildFilterUI(data.branches || []);
      paint();
    }

    function refreshHint() {
      var dict = I18N();
      return location.protocol === "file:"
        ? dict.refresh_fail_file || dict.refresh_fail || "Failed"
        : dict.refresh_fail_http || dict.refresh_fail || "Failed";
    }

    function refreshData() {
      var btn = document.getElementById("btn-refresh");
      var dict = I18N();
      if (btn) btn.disabled = true;
      var s = document.createElement("script");
      s.src = "graph-data.js?t=" + Date.now();
      s.onload = function () {
        if (global.GAI_GRAPH_DATA) render(global.GAI_GRAPH_DATA);
        applyI18n();
        showToast(dict.refresh_ok || "OK");
        if (btn) btn.disabled = false;
        s.remove();
      };
      s.onerror = function () {
        showToast(refreshHint());
        if (btn) btn.disabled = false;
        s.remove();
      };
      document.head.appendChild(s);
    }

    document.getElementById("btn-refresh").addEventListener("click", refreshData);
    document.getElementById("btn-all").addEventListener("click", function () {
      setSelection("all");
    });
    document.getElementById("btn-none").addEventListener("click", function () {
      setSelection("none");
    });
    document.getElementById("btn-current").addEventListener("click", function () {
      setSelection("current");
    });
    document.getElementById("btn-close-detail").addEventListener("click", closeDetail);

    var btnCollapse = document.getElementById("btn-collapse");
    var btnExpand = document.getElementById("btn-expand");
    if (btnCollapse) {
      btnCollapse.addEventListener("click", function () {
        collapseLinear = true;
        expanded = {};
        paint();
      });
    }
    if (btnExpand) {
      btnExpand.addEventListener("click", function () {
        collapseLinear = false;
        paint();
      });
    }

    document.getElementById("btn-lang").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-lang") === "cn" ? "en" : "cn";
      document.documentElement.setAttribute("data-lang", cur);
      document.documentElement.lang = cur === "cn" ? "zh-CN" : "en";
      try {
        localStorage.setItem(prefLang, cur);
      } catch (e) {}
      applyI18n();
      updateRepoMeta();
      paint();
    });
    document.getElementById("btn-theme").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", cur);
      try {
        localStorage.setItem(prefTheme, cur);
      } catch (e) {}
      paint();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeDetail();
    });

    applyI18n();
    render(data);
  }

  global.GaiGraphApp = {
    createApp: createApp,
    COLORS: COLORS,
    ROW_H: ROW_H,
    NODE_W: NODE_W,
    assignCommitColors: assignCommitColors,
    assignLanes: assignLanes,
    planLinearFolds: planLinearFolds,
    buildVisibleModel: buildVisibleModel,
    drawCellSvg: drawCellSvg,
  };
})(typeof window !== "undefined" ? window : this);
