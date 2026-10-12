/**
 * IDEA-like VCS Log graph painter for gai graph.
 * Geometry follows JetBrains SimpleGraphCellPainter:
 * vertical/diagonal edges, dashed+arrow for collapsed linear segments.
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

  var ROW_H = 24;
  var NODE_W = 13;
  var LINE_W = 1.6;
  var CIRCLE_R = 3.6;
  var ARROW_LEN = 0.32; /* fraction of row height */
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
    var map = {};
    (commits || []).forEach(function (c) {
      map[c.hash] = c;
    });
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

  /** Newest-first lane assignment (IDEA / git metro). */
  function assignLanes(commits) {
    var map = {};
    commits.forEach(function (c) {
      map[c.hash] = c;
    });
    var columns = [];
    var rows = [];
    var prevAfter = [];
    commits.forEach(function (c) {
      var arrivedFromAbove = columns.indexOf(c.hash) >= 0;
      var col = columns.indexOf(c.hash);
      if (col < 0) {
        col = columns.indexOf(null);
        if (col < 0) {
          col = columns.length;
          columns.push(c.hash);
        } else {
          columns[col] = c.hash;
        }
      }
      var before = columns.slice();
      var next = columns.slice();
      next[col] = null;
      var parents = (c.parents || []).filter(function (p) {
        return !!map[p];
      });
      var placedFirst = false;
      parents.forEach(function (p) {
        if (next.indexOf(p) >= 0) return;
        if (!placedFirst) {
          next[col] = p;
          placedFirst = true;
        } else {
          var free = next.indexOf(null);
          if (free < 0) next.push(p);
          else next[free] = p;
        }
      });
      while (next.length && next[next.length - 1] === null) next.pop();
      var parentCols = parents.map(function (p) {
        var idx = next.indexOf(p);
        return idx < 0 ? col : idx;
      });
      rows.push({
        commit: c,
        col: col,
        before: before,
        after: next.slice(),
        prevAfter: prevAfter.slice(),
        arrivedFromAbove: arrivedFromAbove,
        parents: parents,
        parentCols: parentCols,
      });
      prevAfter = next.slice();
      columns = next;
    });
    return rows;
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

  /**
   * Collapse linear middles: remove them from visible rows and attach a
   * dashed+arrow down-edge on the commit above each folded segment (IDEA style).
   */
  function collapseRows(rows, children, tips, collapseMin, expanded) {
    var min = Math.max(1, collapseMin || COLLAPSE_MIN);
    var out = [];
    var i = 0;
    while (i < rows.length) {
      if (!isOrdinary(rows[i].commit, children, tips)) {
        out.push(Object.assign({ type: "commit", fold: null }, rows[i]));
        i++;
        continue;
      }
      var start = i;
      while (i < rows.length && isOrdinary(rows[i].commit, children, tips)) i++;
      var run = i - start;
      if (run < min) {
        for (var k = start; k < i; k++) out.push(Object.assign({ type: "commit", fold: null }, rows[k]));
        continue;
      }
      var hashes = [];
      for (var k2 = start; k2 < i; k2++) hashes.push(rows[k2].commit.hash);
      var sid = hashes[0] + ".." + hashes[hashes.length - 1];
      if (expanded[sid]) {
        for (var k3 = start; k3 < i; k3++) out.push(Object.assign({ type: "commit", fold: null }, rows[k3]));
      } else {
        /* Attach fold marker to previous visible commit if any; else keep first of run visible with arrow down. */
        var fold = { id: sid, count: run, hashes: hashes, col: rows[start].col };
        if (out.length && out[out.length - 1].type === "commit") {
          out[out.length - 1].fold = fold;
        } else {
          var keep = Object.assign({ type: "commit", fold: fold }, rows[start]);
          out.push(keep);
          /* skip the rest of the run (already represented by fold) */
        }
      }
    }
    return out;
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
      '<line x1="' +
        tipX +
        '" y1="' +
        tipY +
        '" x2="' +
        a.x +
        '" y2="' +
        a.y +
        '" stroke="' +
        color +
        '" stroke-width="' +
        LINE_W +
        '" stroke-linecap="round"/>'
    );
    parts.push(
      '<line x1="' +
        tipX +
        '" y1="' +
        tipY +
        '" x2="' +
        b.x +
        '" y2="' +
        b.y +
        '" stroke="' +
        color +
        '" stroke-width="' +
        LINE_W +
        '" stroke-linecap="round"/>'
    );
  }

  /**
   * Paint one graph cell like SimpleGraphCellPainter.
   * Diagonals extend half a row so adjacent cells dock.
   */
  function drawCellSvg(row, opts) {
    opts = opts || {};
    var before = row.before || [];
    var after = row.after || [];
    var laneCount = Math.max(before.length, after.length, row.col + 1, 1);
    var w = Math.max(NODE_W * laneCount + 4, NODE_W + 4);
    var h = ROW_H;
    var mid = h / 2;
    var parts = [];
    parts.push(
      '<svg xmlns="http://www.w3.org/2000/svg" width="' +
        w +
        '" height="' +
        h +
        '" viewBox="0 0 ' +
        w +
        " " +
        h +
        '" class="graph-svg">'
    );

    function colColor(j) {
      return colorOf(j);
    }

    /* Pass 1: through-lanes (not the commit's own column). */
    var prevAfter = row.prevAfter || [];
    var maxL = Math.max(before.length, after.length, prevAfter.length, 1);
    for (var j = 0; j < maxL; j++) {
      if (j === row.col) continue;
      var top = prevAfter[j] != null;
      var bot = after[j] != null;
      if (!top && !bot) continue;
      var x = laneX(j);
      var c = colColor(j);
      if (top && bot) {
        parts.push(
          '<line x1="' +
            x +
            '" y1="0" x2="' +
            x +
            '" y2="' +
            h +
            '" stroke="' +
            c +
            '" stroke-width="' +
            LINE_W +
            '"/>'
        );
      } else if (top) {
        parts.push(
          '<line x1="' +
            x +
            '" y1="0" x2="' +
            x +
            '" y2="' +
            mid +
            '" stroke="' +
            c +
            '" stroke-width="' +
            LINE_W +
            '"/>'
        );
      } else {
        parts.push(
          '<line x1="' +
            x +
            '" y1="' +
            mid +
            '" x2="' +
            x +
            '" y2="' +
            h +
            '" stroke="' +
            c +
            '" stroke-width="' +
            LINE_W +
            '"/>'
        );
      }
    }

    var cx = laneX(row.col);
    var main = colColor(row.col);
    var fold = row.fold;
    var hasFoldArrow = !!(fold && fold.count);

    /* Incoming vertical only when this commit continues a lane from above. */
    if (row.arrivedFromAbove) {
      parts.push(
        '<line x1="' +
          cx +
          '" y1="0" x2="' +
          cx +
          '" y2="' +
          mid +
          '" stroke="' +
          main +
          '" stroke-width="' +
          LINE_W +
          '"/>'
      );
    }

    /* Down edges to parents (IDEA: vertical or diagonal into next row). */
    var parentCols = row.parentCols || [];
    if (!parentCols.length && !hasFoldArrow) {
      /* root: no down edge */
    } else if (hasFoldArrow) {
      /* Collapsed linear: dotted vertical + down arrow (IDEA Collapse Linear Branches). */
      var arrowGap = CIRCLE_R / 2 + 1;
      var yTip = h - arrowGap;
      parts.push(
        '<line x1="' +
          cx +
          '" y1="' +
          mid +
          '" x2="' +
          cx +
          '" y2="' +
          yTip +
          '" stroke="' +
          main +
          '" stroke-width="' +
          LINE_W +
          '" stroke-dasharray="2.5 2.5"/>'
      );
      paintArrowHead(parts, cx, mid, cx, yTip, main);
      /* Invisible fat hit target for the arrow */
      parts.push(
        '<rect class="fold-hit" data-fold="' +
          escapeHtml(fold.id) +
          '" data-count="' +
          fold.count +
          '" x="' +
          (cx - 7) +
          '" y="' +
          (mid + 2) +
          '" width="14" height="' +
          (h - mid - 2) +
          '" fill="transparent" style="cursor:pointer"/>'
      );
    } else {
      parentCols.forEach(function (pc) {
        var px = laneX(pc);
        var c2 = colColor(pc);
        if (pc === row.col) {
          parts.push(
            '<line x1="' +
              cx +
              '" y1="' +
              mid +
              '" x2="' +
              cx +
              '" y2="' +
              h +
              '" stroke="' +
              c2 +
              '" stroke-width="' +
              LINE_W +
              '"/>'
          );
        } else {
          /* Diagonal down spanning into next cell (y = h + h/2), clipped visually by overflow visible */
          var y2 = h + h / 2;
          parts.push(
            '<line x1="' +
              cx +
              '" y1="' +
              mid +
              '" x2="' +
              px +
              '" y2="' +
              y2 +
              '" stroke="' +
              c2 +
              '" stroke-width="' +
              LINE_W +
              '" stroke-linecap="round"/>'
          );
        }
      });
    }

    /* Node circle on top */
    parts.push(
      '<circle cx="' +
        cx +
        '" cy="' +
        mid +
        '" r="' +
        CIRCLE_R +
        '" fill="' +
        main +
        '" stroke="' +
        main +
        '"/>'
    );
    if (opts.selected) {
      parts.push(
        '<circle cx="' +
          cx +
          '" cy="' +
          mid +
          '" r="' +
          (CIRCLE_R + 2.2) +
          '" fill="none" stroke="' +
          main +
          '" stroke-width="1.2" opacity="0.55"/>'
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
    var collapseAll = true;

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
      box.innerHTML = "";
      (branches || []).forEach(function (b, i) {
        if (selected[b.name] === undefined) selected[b.name] = true;
        var lab = document.createElement("label");
        if (b.current) lab.className = "current";
        lab.innerHTML =
          '<input type="checkbox" data-branch="' +
          escapeHtml(b.name) +
          '"' +
          (selected[b.name] ? " checked" : "") +
          " />" +
          '<span class="dot" style="background:' +
          colorOf(i) +
          '"></span>' +
          "<span>" +
          escapeHtml(b.name) +
          (b.current ? " ★" : "") +
          "</span>";
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
      if (mode === "current" && !branches.some(function (b) {
        return selected[b.name];
      }) && branches[0]) {
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
        '<div class="t-sub">' +
        escapeHtml(commit.subject || "") +
        "</div>" +
        '<div class="t-meta">' +
        escapeHtml(commit.short || "") +
        " · " +
        escapeHtml(commit.author || "") +
        "</div>" +
        '<div class="t-meta">' +
        escapeHtml(formatDate(commit.date)) +
        "</div>" +
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
      var refHtml = refs.length
        ? refs
            .map(function (r) {
              var col = r.kind === "tag" ? "#9b6bdf" : bmap[r.name] || colorOf(0);
              if (r.kind === "head") col = "#6e6e6e";
              return (
                '<span class="ref-pill' +
                (r.kind === "head" ? " head" : "") +
                '" style="background:' +
                col +
                '">' +
                escapeHtml(r.name) +
                "</span>"
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
                '<span class="parent-link" data-parent="' +
                escapeHtml(p) +
                '">' +
                escapeHtml(label) +
                escapeHtml(sub) +
                "</span>"
              );
            })
            .join("")
        : escapeHtml(dict.detail_none || "(none)");
      var body = ((c.subject || "") + (c.body ? "\n\n" + c.body : "")).trim();
      document.getElementById("drawer-body").innerHTML =
        '<div class="k">' +
        escapeHtml(dict.detail_hash || "Commit") +
        "</div>" +
        '<div class="v mono">' +
        escapeHtml(c.hash) +
        "</div>" +
        '<div class="k">' +
        escapeHtml(dict.detail_author || "Author") +
        "</div>" +
        '<div class="v">' +
        escapeHtml(c.author || "") +
        (c.email ? " &lt;" + escapeHtml(c.email) + "&gt;" : "") +
        "</div>" +
        '<div class="k">' +
        escapeHtml(dict.detail_date || "Date") +
        "</div>" +
        '<div class="v">' +
        escapeHtml(formatDate(c.date) || c.date || "") +
        "</div>" +
        '<div class="k">' +
        escapeHtml(dict.detail_refs || "Refs") +
        "</div>" +
        '<div class="v">' +
        refHtml +
        "</div>" +
        '<div class="k">' +
        escapeHtml(dict.detail_parents || "Parents") +
        "</div>" +
        '<div class="v">' +
        parentHtml +
        "</div>" +
        '<div class="k">' +
        escapeHtml(dict.detail_body || "Message") +
        "</div>" +
        '<div class="v"><pre class="body">' +
        escapeHtml(body || dict.detail_none || "") +
        "</pre></div>";
      document.querySelectorAll("#drawer-body .parent-link").forEach(function (el) {
        el.addEventListener("click", function () {
          openDetail(el.getAttribute("data-parent"));
          paint();
          var row = document.querySelector(
            'tr.commit-row[data-hash="' + el.getAttribute("data-parent") + '"]'
          );
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

      if (!(data.commits || []).length) {
        empty.hidden = false;
        table.hidden = true;
        document.getElementById("empty-text").textContent = I18N().empty || "Empty";
        return;
      }
      if (!commits.length) {
        empty.hidden = false;
        table.hidden = true;
        document.getElementById("empty-text").textContent =
          I18N().empty_filter || I18N().empty || "Empty";
        return;
      }
      empty.hidden = true;
      table.hidden = false;

      var tips = tipMap(data.branches);
      var children = buildChildren(commits);
      var lanes = assignLanes(commits);
      var expMap = collapseAll ? expanded : {};
      /* If expand-all mode: treat every segment as expanded */
      if (!collapseAll) {
        expMap = {};
        /* force expand by marking all potential sids — easier: skip collapse */
      }
      var visible = collapseAll
        ? collapseRows(lanes, children, tips, data.collapseMin || COLLAPSE_MIN, expanded)
        : lanes.map(function (r) {
            return Object.assign({ type: "commit", fold: null }, r);
          });

      var bmap = branchColorMap(data.branches);
      var dict = I18N();
      var maxGraphW = NODE_W + 4;

      visible.forEach(function (row) {
        var c = row.commit;
        var tr = document.createElement("tr");
        tr.className = "commit-row" + (activeHash === c.hash ? " active" : "");
        tr.setAttribute("data-hash", c.hash);
        var painted = drawCellSvg(row, { selected: activeHash === c.hash });
        if (painted.width > maxGraphW) maxGraphW = painted.width;

        var refs = refsFor(c, tips);
        var pills = refs
          .map(function (r) {
            var col = r.kind === "tag" ? "#9b6bdf" : bmap[r.name] || colorOf(0);
            if (r.kind === "head") col = "#6e6e6e";
            return (
              '<span class="ref-pill' +
              (r.kind === "head" ? " head" : "") +
              '" style="background:' +
              col +
              '">' +
              escapeHtml(r.name) +
              "</span>"
            );
          })
          .join("");

        tr.innerHTML =
          '<td class="graph-cell">' +
          painted.html +
          "</td>" +
          '<td class="msg-cell"><div class="msg">' +
          pills +
          '<span class="subject">' +
          escapeHtml(c.subject || "") +
          "</span></div></td>" +
          '<td class="author">' +
          escapeHtml(c.author || "") +
          "</td>" +
          '<td class="date">' +
          escapeHtml(formatDate(c.date)) +
          "</td>" +
          '<td class="hash">' +
          escapeHtml(c.short || "") +
          "</td>";

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
            showTooltip('<div class="t-sub">' + escapeHtml(msg) + "</div><div class=\"t-meta\">" +
              escapeHtml(dict.collapse_hint || "") +
              "</div>", ev);
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
        el.style.width = maxGraphW + 8 + "px";
      });

      if (activeHash && byHash[activeHash]) {
        /* refresh highlight without rebuilding drawer content thrash */
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
        collapseAll = true;
        expanded = {};
        paint();
      });
    }
    if (btnExpand) {
      btnExpand.addEventListener("click", function () {
        collapseAll = false;
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

  global.GaiGraphApp = { createApp: createApp, COLORS: COLORS };
})(typeof window !== "undefined" ? window : this);
