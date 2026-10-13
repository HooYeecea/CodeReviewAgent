/**
 * gai graph — ECharts node-link commit graph (linked-list / topology feel).
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

  var COLLAPSE_MIN = 3;
  /** Column / row spacing in cartesian units (1 row ≈ one clear node slot). */
  var X_UNIT = 1.6;
  var Y_UNIT = 1;
  /** How many commits fit in the default vertical window (readable links). */
  var VIEW_ROWS = 12;

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

  /** Newest-first lane columns for hierarchical X placement. */
  function assignLanes(commits) {
    var map = indexByHash(commits);
    var columns = [];
    var rows = [];
    commits.forEach(function (c) {
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
      rows.push({ commit: c, col: col, parents: parents });
      columns = next;
    });
    return rows;
  }

  function buildVisibleModel(commits, branches, tips, opts) {
    opts = opts || {};
    var children = buildChildren(commits);
    var commitColors = assignCommitColors(commits, branches);
    /* Default expanded; only collapse when explicitly requested. */
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
    var lanes = assignLanes(visibleCommits);
    lanes.forEach(function (r) {
      r.color = commitColors[r.commit.hash] || colorOf(r.col);
      r.fold = foldsByAbove[r.commit.hash] || null;
    });
    return { rows: lanes, commitColors: commitColors, hidden: hidden };
  }

  /** Build ECharts graph nodes/links from lane rows. */
  function toEchartsGraph(rows, tips, bmap, dark) {
    var nodes = [];
    var links = [];
    var categories = [];
    var catIndex = {};
    Object.keys(bmap || {}).forEach(function (name, i) {
      catIndex[name] = i;
      categories.push({ name: name, itemStyle: { color: bmap[name] } });
    });
    if (!categories.length) {
      categories.push({ name: "commits", itemStyle: { color: COLORS[0] } });
    }

    rows.forEach(function (r, idx) {
      var c = r.commit;
      var refs = refsFor(c, tips);
      var branchNames = refs
        .filter(function (x) {
          return x.kind === "branch";
        })
        .map(function (x) {
          return x.name;
        });
      var cat = 0;
      for (var bi = 0; bi < branchNames.length; bi++) {
        if (catIndex[branchNames[bi]] !== undefined) {
          cat = catIndex[branchNames[bi]];
          break;
        }
      }
      var labelBits = [];
      refs.forEach(function (ref) {
        if (ref.kind === "head") labelBits.push("HEAD");
        else labelBits.push(ref.name);
      });
      var title = (c.subject || "").slice(0, 42);
      if ((c.subject || "").length > 42) title += "…";
      var nodeLabel = (c.short || c.hash.slice(0, 7)) + (title ? "\n" + title : "");
      if (labelBits.length) nodeLabel = labelBits.join(" · ") + "\n" + nodeLabel;

      var size = refs.length ? 46 : 36;
      if (r.fold && r.fold.count) size = 42;

      nodes.push({
        id: c.hash,
        name: c.short || c.hash.slice(0, 7),
        /* cartesian2d: [col, row]; keep hash on commit for click handlers */
        value: [r.col * X_UNIT, idx * Y_UNIT],
        category: cat,
        symbolSize: size,
        itemStyle: {
          color: r.color,
          borderColor: dark ? "#fff" : "#1a1d23",
          borderWidth: refs.length ? 2.5 : 1.5,
          shadowBlur: 8,
          shadowColor: "rgba(0,0,0,0.18)",
        },
        /* Details hidden by default; shown on hover (emphasis) / selected click. */
        label: {
          show: false,
          position: "right",
          distance: 14,
          formatter: nodeLabel,
          color: dark ? "#e8eaed" : "#1a1d23",
          fontSize: 12,
          lineHeight: 16,
          fontFamily: 'Segoe UI, "Helvetica Neue", sans-serif',
          backgroundColor: dark ? "rgba(27,32,40,0.92)" : "rgba(255,255,255,0.94)",
          padding: [6, 8],
          borderRadius: 6,
          borderColor: dark ? "#3a4250" : "#d0d7e2",
          borderWidth: 1,
        },
        commit: c,
        fold: r.fold,
        col: r.col,
        row: idx,
      });

      (r.parents || []).forEach(function (p) {
        var isFold = !!(r.fold && r.fold.belowHash === p);
        links.push({
          source: c.hash,
          target: p,
          lineStyle: {
            color: r.color,
            width: isFold ? 2 : 2.4,
            type: isFold ? "dashed" : "solid",
            curveness: r.col !== (rows.find(function (x) {
              return x.commit.hash === p;
            }) || { col: r.col }).col
              ? 0.18
              : 0.05,
            opacity: 0.85,
          },
          symbol: ["none", "arrow"],
          symbolSize: [0, 10],
        });
      });
    });

    return { nodes: nodes, links: links, categories: categories };
  }

  /**
   * Default vertical window for cartesian dataZoom — shows ~VIEW_ROWS commits
   * so edges stay readable (not a glued pillar of the entire history).
   */
  function computeDataZoomWindow(nodes) {
    var n = Math.max((nodes && nodes.length) || 1, 1);
    var maxCol = 0;
    (nodes || []).forEach(function (node) {
      var col = (node.value && node.value[0]) || 0;
      if (col > maxCol) maxCol = col;
    });
    var yEnd = Math.min(n - 0.35, VIEW_ROWS - 0.35);
    if (n <= VIEW_ROWS) yEnd = n - 0.35;
    return {
      yStart: -0.55,
      yEnd: Math.max(yEnd, 0.55),
      xStart: -0.9,
      xEnd: Math.max(maxCol + 1.8, 2.2),
      yMax: Math.max(n - 0.25, VIEW_ROWS),
      xMax: Math.max(maxCol + 1.8, 2.2),
    };
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
    var chart = null;
    var foldByHash = {};
    var savedZoom = null;
    var resetViewOnPaint = true;

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
          '<input type="checkbox" data-branch="' +
          escapeHtml(b.name) +
          '"' +
          (selected[b.name] ? " checked" : "") +
          " />" +
          '<span class="dot" style="background:' +
          (bmap[b.name] || colorOf(0)) +
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
          resetViewOnPaint = true;
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
      resetViewOnPaint = true;
      buildFilterUI(branches);
      paint();
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
      var foldBtn = "";
      var foldMeta = foldByHash[hash] || null;
      if (foldMeta && foldMeta.id && foldMeta.count) {
        foldBtn =
          '<div style="margin-top:12px"><button type="button" id="btn-expand-fold" data-fold="' +
          escapeHtml(foldMeta.id) +
          '">' +
          escapeHtml((dict.expand || "Expand {n} commits").replace("{n}", String(foldMeta.count))) +
          "</button></div>";
      }
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
        "</pre></div>" +
        foldBtn;
      document.querySelectorAll("#drawer-body .parent-link").forEach(function (el) {
        el.addEventListener("click", function () {
          openDetail(el.getAttribute("data-parent"));
        });
      });
      var expFold = document.getElementById("btn-expand-fold");
      if (expFold) {
        expFold.addEventListener("click", function () {
          resetViewOnPaint = false;
          expanded[expFold.getAttribute("data-fold")] = true;
          paint();
        });
      }
    }

    function closeDetail() {
      activeHash = null;
      document.getElementById("layout").classList.add("no-detail");
      if (chart) {
        try {
          chart.resize();
        } catch (e) {}
      }
    }

    function ensureChart() {
      var el = document.getElementById("graph-chart");
      if (!el) return null;
      if (typeof global.echarts === "undefined") return null;
      if (!chart) {
        chart = global.echarts.init(el, null, { renderer: "canvas" });
        chart.on("click", function (params) {
          if (params.dataType === "node" && params.data) {
            var hash = params.data.id || (params.data.commit && params.data.commit.hash);
            if (!hash) return;
            activeHash = hash;
            resetViewOnPaint = false;
            openDetail(hash);
            paint();
          }
        });
        chart.on("dblclick", function (params) {
          if (params.dataType === "node" && params.data && params.data.fold && params.data.fold.id) {
            resetViewOnPaint = false;
            expanded[params.data.fold.id] = true;
            paint();
          }
        });
        chart.on("datazoom", function () {
          try {
            var opt = chart.getOption();
            var dz = opt.dataZoom || [];
            savedZoom = dz.map(function (z) {
              return {
                startValue: z.startValue,
                endValue: z.endValue,
                start: z.start,
                end: z.end,
              };
            });
          } catch (e) {}
        });
        window.addEventListener("resize", function () {
          if (chart) chart.resize();
        });
      }
      return chart;
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
      var host = document.getElementById("graph-chart");
      var dict = I18N();

      if (!(data.commits || []).length) {
        empty.hidden = false;
        if (host) host.hidden = true;
        document.getElementById("empty-text").textContent = dict.empty || "Empty";
        return;
      }
      if (!commits.length) {
        empty.hidden = false;
        if (host) host.hidden = true;
        document.getElementById("empty-text").textContent =
          dict.empty_filter || dict.empty || "Empty";
        return;
      }

      if (typeof global.echarts === "undefined") {
        empty.hidden = false;
        if (host) host.hidden = true;
        document.getElementById("empty-text").textContent =
          dict.echarts_fail || "Failed to load ECharts. Check network / CDN.";
        return;
      }

      empty.hidden = true;
      if (host) host.hidden = false;

      var tips = tipMap(data.branches);
      var model = buildVisibleModel(commits, data.branches || [], tips, {
        collapseLinear: collapseLinear,
        expanded: expanded,
        collapseMin: data.collapseMin || COLLAPSE_MIN,
      });
      /* Mark fold hosts so double-click / button can expand — also show count in label via fold */
      foldByHash = {};
      model.rows.forEach(function (r) {
        if (r.fold && r.fold.count) foldByHash[r.commit.hash] = r.fold;
      });

      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      var bmap = branchColorMap(data.branches);
      var g = toEchartsGraph(model.rows, tips, bmap, dark);

      g.nodes.forEach(function (n) {
        if (n.fold && n.fold.count) {
          var tip = (dict.expand || "Expand {n} commits").replace("{n}", String(n.fold.count));
          n.label.formatter = (n.label.formatter || n.name) + "\n▾ " + tip;
          n.foldClick = true;
          /* Tiny fold cue on the node itself (not full commit text). */
          n.symbol = "circle";
          n.itemStyle = Object.assign({}, n.itemStyle, {
            borderWidth: 3,
            borderColor: dark ? "#ffd54f" : "#f9a825",
          });
        }
        if (activeHash && n.commit && n.commit.hash === activeHash) {
          n.label = Object.assign({}, n.label, { show: true });
          n.itemStyle = Object.assign({}, n.itemStyle, {
            borderWidth: 4,
            shadowBlur: 16,
          });
        }
      });

      var c = ensureChart();
      if (!c) return;

      c.resize();
      var win = computeDataZoomWindow(g.nodes);
      var yZoom = {
        type: "inside",
        id: "y-zoom",
        yAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
        startValue: win.yStart,
        endValue: win.yEnd,
      };
      var xZoom = {
        type: "inside",
        id: "x-zoom",
        xAxisIndex: 0,
        filterMode: "none",
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        startValue: win.xStart,
        endValue: win.xEnd,
      };
      if (!resetViewOnPaint && savedZoom && savedZoom.length >= 2) {
        if (savedZoom[0].startValue != null && savedZoom[0].endValue != null) {
          yZoom.startValue = savedZoom[0].startValue;
          yZoom.endValue = savedZoom[0].endValue;
        }
        if (savedZoom[1].startValue != null && savedZoom[1].endValue != null) {
          xZoom.startValue = savedZoom[1].startValue;
          xZoom.endValue = savedZoom[1].endValue;
        }
      } else {
        savedZoom = [
          { startValue: yZoom.startValue, endValue: yZoom.endValue },
          { startValue: xZoom.startValue, endValue: xZoom.endValue },
        ];
      }
      resetViewOnPaint = false;

      c.setOption(
        {
          backgroundColor: "transparent",
          animation: false,
          grid: {
            left: 48,
            right: 120,
            top: 44,
            bottom: 28,
            containLabel: false,
          },
          xAxis: {
            type: "value",
            min: -1,
            max: win.xMax,
            show: false,
            axisPointer: { show: false },
          },
          yAxis: {
            type: "value",
            inverse: true,
            min: -0.8,
            max: win.yMax,
            show: false,
            axisPointer: { show: false },
          },
          dataZoom: [yZoom, xZoom],
          tooltip: {
            trigger: "item",
            enterable: false,
            formatter: function (p) {
              if (p.dataType !== "node" || !p.data || !p.data.commit) {
                return p.name || "";
              }
              var cm = p.data.commit;
              var refs = refsFor(cm, tips)
                .map(function (r) {
                  return r.name;
                })
                .join(", ");
              return (
                "<div style='max-width:360px'>" +
                "<div style='font-weight:600;margin-bottom:4px'>" +
                escapeHtml(cm.subject || "") +
                "</div>" +
                "<div style='opacity:.75;font-family:monospace;font-size:11px'>" +
                escapeHtml(cm.short || "") +
                " · " +
                escapeHtml(cm.author || "") +
                "</div>" +
                "<div style='opacity:.75;font-size:11px'>" +
                escapeHtml(formatDate(cm.date)) +
                "</div>" +
                (refs
                  ? "<div style='opacity:.75;font-size:11px;margin-top:2px'>" +
                    escapeHtml(refs) +
                    "</div>"
                  : "") +
                (p.data.fold && p.data.fold.count
                  ? "<div style='margin-top:4px;opacity:.85'>" +
                    escapeHtml(
                      (dict.expand || "Expand {n}").replace("{n}", String(p.data.fold.count))
                    ) +
                    " — " +
                    escapeHtml(dict.collapse_hint || "dblclick to expand") +
                    "</div>"
                  : "") +
                "</div>"
              );
            },
          },
          legend: {
            type: "scroll",
            orient: "horizontal",
            top: 8,
            left: 12,
            z: 2,
            textStyle: { color: dark ? "#c8c8c8" : "#444", fontSize: 11 },
            data: g.categories.map(function (x) {
              return x.name;
            }),
          },
          series: [
            {
              id: "gai-commit-graph",
              type: "graph",
              coordinateSystem: "cartesian2d",
              layout: "none",
              roam: false,
              draggable: false,
              categories: g.categories,
              data: g.nodes,
              links: g.links,
              edgeSymbol: ["none", "arrow"],
              edgeSymbolSize: [0, 12],
              lineStyle: {
                opacity: 0.92,
                width: 2.6,
                curveness: 0.12,
              },
              emphasis: {
                focus: "adjacency",
                scale: true,
                label: { show: true },
                lineStyle: { width: 3.8 },
                itemStyle: { shadowBlur: 18 },
              },
              blur: {
                label: { show: false },
                itemStyle: { opacity: 0.3 },
                lineStyle: { opacity: 0.15 },
              },
              labelLayout: { hideOverlap: true },
              selectedMode: false,
            },
          ],
        },
        { notMerge: true, lazyUpdate: false }
      );

      if (activeHash && byHash[activeHash]) {
        openDetail(activeHash);
      }
    }

    function render(d) {
      data = d || data;
      (data.branches || []).forEach(function (b) {
        if (selected[b.name] === undefined) selected[b.name] = true;
      });
      resetViewOnPaint = true;
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
        resetViewOnPaint = true;
        paint();
      });
    }
    if (btnExpand) {
      btnExpand.addEventListener("click", function () {
        collapseLinear = false;
        resetViewOnPaint = true;
        paint();
      });
    }
    var btnFit = document.getElementById("btn-fit");
    if (btnFit) {
      btnFit.addEventListener("click", function () {
        resetViewOnPaint = true;
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

    /* Expand fold when clicking a node that has fold — first click expands if collapsed host */
    /* Handled in chart click: if foldClick, expand */

    applyI18n();
    render(data);
  }

  global.GaiGraphApp = {
    createApp: createApp,
    COLORS: COLORS,
    assignCommitColors: assignCommitColors,
    assignLanes: assignLanes,
    planLinearFolds: planLinearFolds,
    buildVisibleModel: buildVisibleModel,
    toEchartsGraph: toEchartsGraph,
    computeDataZoomWindow: computeDataZoomWindow,
  };
})(typeof window !== "undefined" ? window : this);
