/* Project Atlas map component: automatic layout, SVG drawing, interaction, side panel.
   Used by the standalone map page and by the branch report. */
var AtlasMap = (function () {
  "use strict";
  var W = 1020, GUT = 108, MOD_H = 38, ROW = 46;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function textWidth(s, px) {
    var w = 0;
    for (var ch of String(s)) w += ch.charCodeAt(0) > 0x2e80 ? px : px * 0.62;
    return w;
  }
  function modWidth(label, sub) { return Math.min(190, Math.max(56, Math.ceil(Math.max(textWidth(label, 11.5), textWidth(sub || "", 9.5))) + 18)); }
  function clip(label, width, px) {
    if (textWidth(label, px) + 18 <= width) return label;
    var out = "";
    for (var ch of String(label)) {
      if (textWidth(out + ch + "…", px) + 18 > width) break;
      out += ch;
    }
    return out + "…";
  }
  function fmt(n, lang) { return n == null ? "—" : Number(n).toLocaleString(lang === "zh" ? "zh-CN" : "en-US"); }

  function subText(m, t, lang) { return m.kind === "external" ? (m.version || t("third_party")) : t("n_loc", { n: fmt(m.loc, lang) }); }

  function visibleIds(model, overlayOn) {
    var ov = model.overlay, vis = {};
    Object.keys(model.modules).forEach(function (id) {
      var st = ov && ov.status[id];
      if (!overlayOn && st === "new") return;
      vis[id] = true;
    });
    return vis;
  }

  /* Bands per layer; groups packed left to right; modules packed into rows inside a group. */
  function layout(model, view, vis, t, lang) {
    var y = 16, bands = [], gpos = {}, mpos = {};
    model.layers.forEach(function (layer) {
      var gs = model.groups.filter(function (g) { return g.layer === layer.id && g.modules.some(function (id) { return vis[id]; }); });
      if (!gs.length) return;
      var top = y, x = GUT, rowTop = y + 16, rowH = 0;
      gs.forEach(function (g) {
        var ids = g.modules.filter(function (id) { return vis[id]; });
        var w, h, rows = [];
        var nameW = Math.ceil(textWidth(g.name, 11.5));
        if (view === "module") {
          var widths = ids.map(function (id) { var m = model.modules[id]; return modWidth(m.label, t ? subText(m, t, lang) : ""); });
          var total = widths.reduce(function (a, b) { return a + b; }, 0) + 8 * (ids.length - 1);
          var nrows = Math.max(1, Math.round(Math.sqrt(ids.length / 2.5)));
          var maxRow = Math.min(W - GUT - 40, Math.max(Math.max.apply(null, widths), Math.ceil(total / nrows) + 8, nameW));
          var cur = [], cw = 0;
          ids.forEach(function (id, i) {
            if (cur.length && cw + 8 + widths[i] > maxRow) { rows.push(cur); cur = []; cw = 0; }
            cw += (cur.length ? 8 : 0) + widths[i];
            cur.push([id, widths[i]]);
          });
          if (cur.length) rows.push(cur);
          var inner = Math.max.apply(null, rows.map(function (r) {
            return r.reduce(function (a, c, k) { return a + c[1] + (k ? 8 : 0); }, 0);
          }));
          w = Math.min(W - GUT - 16, Math.max(inner, nameW) + 24);
          h = 24 + rows.length * ROW - 8 + 10;
        } else {
          w = Math.min(240, Math.max(112, Math.ceil(textWidth(g.name, 13.5)) + 36));
          h = 64;
        }
        if (x + w > W - 16 && x > GUT) { x = GUT; rowTop += rowH + 14; rowH = 0; }
        gpos[g.id] = { x: x, y: rowTop, w: w, h: h };
        rows.forEach(function (r, ri) {
          var mx = x + 12;
          r.forEach(function (c) {
            mpos[c[0]] = { x: mx, y: rowTop + 24 + ri * ROW, w: c[1], h: MOD_H, g: g.id };
            mx += c[1] + 8;
          });
        });
        x += w + 20;
        rowH = Math.max(rowH, h);
      });
      var bottom = rowTop + rowH + 16;
      bands.push({ id: layer.id, name: layer.name, y: top, h: bottom - top });
      y = bottom + 14;
    });
    return { width: W, height: Math.max(y, 120), bands: bands, groups: gpos, mods: mpos };
  }

  function bandLabel(name, x, y) {
    var max = GUT - 24, words = String(name).split(/\s+/), lines = [], cur = "";
    words.forEach(function (w) {
      var next = cur ? cur + " " + w : w;
      if (cur && textWidth(next, 13) > max) { lines.push(cur); cur = w; } else cur = next;
    });
    if (cur) lines.push(cur);
    var px = lines.some(function (l) { return textWidth(l, 13) > max; }) ? 11 : 13;
    return '<text class="bandl" x="' + x + '" y="' + y + '" style="font-size:' + px + 'px">' + lines.slice(0, 3).map(function (l, i) {
      return '<tspan x="' + x + '" dy="' + (i ? px + 3 : 0) + '">' + esc(textWidth(l, px) > GUT - 12 ? clip(l, GUT + 6, px) : l) + "</tspan>";
    }).join("") + "</text>";
  }

  function edgePath(A, B) {
    var ax = A.x + A.w / 2, bx = B.x + B.w / 2, y1, y2;
    if (B.y >= A.y + A.h) { y1 = A.y + A.h; y2 = B.y; }
    else if (B.y + B.h <= A.y) { y1 = A.y; y2 = B.y + B.h; }
    else {
      var t = Math.min(A.y, B.y) - 22;
      return "M" + ax + "," + A.y + " C" + ax + "," + t + " " + bx + "," + t + " " + bx + "," + B.y;
    }
    var my = (y1 + y2) / 2;
    return "M" + ax + "," + y1 + " C" + ax + "," + my + " " + bx + "," + my + " " + bx + "," + y2;
  }
  function seg(a, b, lift) {
    var dy = b.y - a.y;
    if (Math.abs(dy) < 20) return "C" + a.x + "," + (a.y - lift) + " " + b.x + "," + (b.y - lift) + " " + b.x + "," + b.y;
    return "C" + a.x + "," + (a.y + dy / 2) + " " + b.x + "," + (b.y - dy / 2) + " " + b.x + "," + b.y;
  }

  /* ------------------------------------------------------------------ component */

  function create(root, model, opts) {
    var t = opts.t, lang = opts.lang;
    var ov = model.overlay || null;
    var S = { view: opts.view || "module", overlay: !!ov, flows: model.flows.length > 0, deps: false,
              flow: null, sel: null, hover: null };
    var groupOf = {}, groupById = {};
    model.groups.forEach(function (g) { groupById[g.id] = g; g.modules.forEach(function (m) { groupOf[m] = g.id; }); });
    var layerName = {};
    model.layers.forEach(function (l) { layerName[l.id] = l.name; });
    var vis, L, nodes, edges;

    root.innerHTML =
      '<div class="controls">' +
        '<div class="ctl"><span class="label">' + esc(t("view")) + '</span><div class="seg" data-ctl="view" role="group">' +
          '<button type="button" data-v="domain">' + esc(t("view_groups")) + '</button><button type="button" data-v="module">' + esc(t("view_modules")) + "</button></div></div>" +
        (ov ? '<div class="ctl"><span class="label">' + esc(t("overlay")) + '</span><div class="seg" data-ctl="overlay" role="group">' +
          '<button type="button" data-v="off">' + esc(t("overlay_off")) + '</button><button type="button" data-v="on" class="mono">' + esc(ov.branch || t("overlay_on")) + "</button></div></div>" : "") +
        '<div class="ctl"><span class="label">' + esc(t("layers")) + "</span>" +
          (model.flows.length ? '<label class="chk-l"><input type="checkbox" data-ctl="flows"> ' + esc(t("layer_flows")) + "</label>" : "") +
          '<label class="chk-l"><input type="checkbox" data-ctl="deps"> ' + esc(t("layer_deps")) + "</label></div>" +
      "</div>" +
      '<div class="mapgrid"><div class="panel"><div class="mapbox"><svg class="atlas-svg" role="group" aria-label="' + esc(t("map_aria")) + '"></svg></div>' +
      '<div class="mapfoot"><div class="info" aria-live="polite"></div><div class="legends"><div class="fchips"></div><div class="slegend"></div></div></div></div>' +
      '<aside class="panel side" aria-live="polite"></aside></div>';
    var svg = root.querySelector("svg"), side = root.querySelector(".side"), info = root.querySelector(".info");

    function stOf(id) {
      if (!ov || !S.overlay) return null;
      if (S.view === "module") return ov.status[id] || null;
      var g = groupById[id];
      if (!g) return null;
      var ss = g.modules.filter(function (m) { return vis[m]; }).map(function (m) { return ov.status[m]; });
      return ss.some(function (s) { return s === "chg" || s === "new" || s === "del"; }) ? "chg" : ss.indexOf("aff") >= 0 ? "aff" : null;
    }
    function groupSub(g) {
      var ids = g.modules.filter(function (m) { return vis[m]; });
      if (!ov || !S.overlay) return t("n_modules", { n: ids.length });
      var c = function (k) { return ids.filter(function (m) { return ov.status[m] === k; }).length; };
      var parts = [["chg", "g_changed"], ["new", "g_new"], ["del", "g_deleted"], ["aff", "g_affected"]]
        .filter(function (p) { return c(p[0]); }).map(function (p) { return t(p[1], { n: c(p[0]) }); });
      return parts.join(" · ") || t("n_modules", { n: ids.length });
    }
    var nodeOf = function (id) { return S.view === "module" ? id : groupOf[id]; };

    function buildEdges() {
      var list = model.edges.filter(function (e) { return vis[e.a] && vis[e.b] && (e.k !== "new" || S.overlay); });
      if (S.view === "module") return list;
      var P = { dep: 0, new: 1, miss: 2 }, agg = {};
      list.forEach(function (e) {
        var a = groupOf[e.a], b = groupOf[e.b];
        if (!a || !b || a === b) return;
        var k = a + ">" + b;
        if (!agg[k] || P[e.k] > P[agg[k].k]) agg[k] = { a: a, b: b, k: e.k };
      });
      return Object.keys(agg).map(function (k) { return agg[k]; });
    }
    function flowNodes(f) {
      var set = {};
      f.chains.forEach(function (c) { c.forEach(function (m) { if (vis[m]) set[nodeOf(m)] = true; }); });
      return set;
    }

    function render() {
      vis = visibleIds(model, S.overlay);
      L = layout(model, S.view, vis, t, lang);
      nodes = {};
      if (S.view === "module") Object.keys(L.mods).forEach(function (id) { nodes[id] = L.mods[id]; });
      else Object.keys(L.groups).forEach(function (id) { nodes[id] = L.groups[id]; });
      edges = buildEdges().filter(function (e) { return nodes[e.a] && nodes[e.b]; });
      svg.setAttribute("viewBox", "0 0 " + L.width + " " + L.height);
      var h = "<defs>" + ["dep", "on", "new", "miss"].map(function (k) {
        return '<marker id="m-' + k + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path class="mk-' + k + '" d="M0,0 L10,5 L0,10 z"/></marker>';
      }).join("") + "</defs>";
      L.bands.forEach(function (b) {
        h += '<rect class="band" x="4" y="' + b.y + '" width="' + (L.width - 8) + '" height="' + b.h + '" rx="10"/>' + bandLabel(b.name, 18, b.y + 26);
      });
      var groupLabels = "";
      if (S.view === "module") {
        model.groups.forEach(function (g) {
          var p = L.groups[g.id];
          if (!p) return;
          h += '<rect class="grp" x="' + p.x + '" y="' + p.y + '" width="' + p.w + '" height="' + p.h + '" rx="8"/>';
          groupLabels += '<text class="grpl" x="' + (p.x + 12) + '" y="' + (p.y + 16) + '">' + esc(clip(g.name, p.w - 6, 11.5)) + "</text>";
        });
      }
      var lift = S.view === "module" ? 36 : 0;
      h += "<g>";
      model.flows.forEach(function (f, k) {
        var o = ((k % 5) - 2) * 4;
        f.chains.forEach(function (chain) {
          var ns = chain.filter(function (m) { return vis[m]; }).map(nodeOf).filter(function (id, i, arr) { return i === 0 || id !== arr[i - 1]; });
          if (ns.length < 2 || ns.some(function (id) { return !nodes[id]; })) return;
          var pts = ns.map(function (id) { var n = nodes[id]; return { x: n.x + n.w / 2 + o, y: n.y + n.h / 2 + o }; });
          var d = "M" + pts[0].x + "," + pts[0].y;
          for (var i = 1; i < pts.length; i++) d += " " + seg(pts[i - 1], pts[i], lift);
          h += '<path class="fl" data-f="' + esc(f.id) + '" style="stroke:var(--f' + f.color + ')" d="' + d + '"/>';
        });
      });
      h += "</g><g>";
      edges.forEach(function (e) {
        h += '<path class="edge ' + e.k + '" data-a="' + esc(e.a) + '" data-b="' + esc(e.b) + '" data-k="' + e.k + '" d="' + edgePath(nodes[e.a], nodes[e.b]) + '" marker-end="url(#m-' + e.k + ')"/>';
      });
      h += "</g><g>" + groupLabels + "</g><g>";
      Object.keys(nodes).forEach(function (id) {
        var n = nodes[id], st = stOf(id);
        var cls = "node" + (S.view === "module" ? " kind-" + model.modules[id].kind : " grpn") + (st ? " s-" + st : (ov && S.overlay ? " quiet" : ""));
        if (S.view === "module") {
          var m = model.modules[id];
          var sub = subText(m, t, lang);
          h += '<g class="' + cls + '" data-id="' + esc(id) + '" tabindex="0" role="button" aria-label="' + esc(m.path + (st ? ", " + t("st_" + st) : "")) + '">' +
               '<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="5"/>' +
               '<text class="nm" x="' + (n.x + 9) + '" y="' + (n.y + 16) + '">' + esc(clip(m.label, n.w, 11.5)) + "</text>" +
               '<text class="sb" x="' + (n.x + 9) + '" y="' + (n.y + 30) + '">' + esc(clip(sub, n.w, 9.5)) + "</text>" +
               (m.fresh === "stale" || m.fresh === "pending" ? '<circle class="stale" cx="' + (n.x + n.w - 1) + '" cy="' + (n.y + 1) + '" r="4.5"/>' : "") +
               "<title>" + esc(m.path) + "</title></g>";
        } else {
          var g = groupById[id], cx = n.x + n.w / 2, cy = n.y + n.h / 2;
          h += '<g class="' + cls + '" data-id="' + esc(id) + '" tabindex="0" role="button" aria-label="' + esc(g.name) + '">' +
               '<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="8"/>' +
               '<text class="gnm" x="' + cx + '" y="' + (cy - 2) + '" text-anchor="middle">' + esc(clip(g.name, n.w, 13.5)) + "</text>" +
               '<text class="gsb" x="' + cx + '" y="' + (cy + 15) + '" text-anchor="middle">' + esc(clip(groupSub(g), n.w, 11)) + "</text></g>";
        }
      });
      h += "</g>";
      svg.innerHTML = h;
      svg.classList.toggle("show-flows", S.flows);
      svg.classList.toggle("show-deps", S.deps);
      svg.querySelectorAll(".node").forEach(bind);
      sync(); legend(); highlight(); panel();
      info.textContent = t("hover_hint");
    }

    function bind(el) {
      var id = el.getAttribute("data-id");
      el.addEventListener("mouseenter", function () { hover(id); });
      el.addEventListener("mouseleave", function () { hover(null); });
      el.addEventListener("focus", function () { hover(id); });
      el.addEventListener("blur", function () { hover(null); });
      el.addEventListener("click", function () { select(S.sel === id ? null : id); });
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(S.sel === id ? null : id); }
      });
    }
    function hover(id) {
      S.hover = id;
      highlight();
      if (!id) { info.textContent = t("hover_hint"); return; }
      if (S.view === "module") {
        var m = model.modules[id], st = stOf(id);
        info.textContent = m.path + " · " + (m.kind === "external" ? t("third_party") : t("n_loc", { n: fmt(m.loc, lang) })) +
          (m.owners.length ? " · " + m.owners.join(" ") : "") + (st ? " · " + t("st_" + st) : "");
      } else {
        var g = groupById[id];
        info.textContent = g.name + " · " + groupSub(g);
      }
    }
    function highlight() {
      var f = S.hover || S.sel;
      svg.classList.toggle("has-focus", !!f);
      svg.classList.toggle("flow-focus", !f && !!S.flow);
      var nb = {};
      svg.querySelectorAll(".edge").forEach(function (e) {
        var a = e.getAttribute("data-a"), b = e.getAttribute("data-b"), k = e.getAttribute("data-k");
        var on = !!f && (a === f || b === f);
        e.classList.toggle("on", on);
        e.setAttribute("marker-end", "url(#m-" + (on && k === "dep" ? "on" : k) + ")");
        if (on) { nb[a] = true; nb[b] = true; }
      });
      var fl = S.flow ? flowNodes(model.flows.filter(function (x) { return x.id === S.flow; })[0]) : null;
      svg.querySelectorAll(".node").forEach(function (n) {
        var id = n.getAttribute("data-id");
        n.classList.toggle("focus", id === f);
        n.classList.toggle("nb", id !== f && !!nb[id]);
        n.classList.toggle("sel", id === S.sel);
        n.classList.toggle("onflow", !!fl && !!fl[id]);
        n.setAttribute("aria-pressed", String(id === S.sel));
      });
      svg.querySelectorAll(".fl").forEach(function (p) {
        var fo = model.flows.filter(function (x) { return x.id === p.getAttribute("data-f"); })[0];
        var on = f ? !!flowNodes(fo)[f] : S.flow ? fo.id === S.flow : true;
        p.classList.toggle("faded", !on);
      });
    }
    function legend() {
      root.querySelector(".fchips").innerHTML = model.flows.map(function (f) {
        var s = flowStatus(f);
        return '<button type="button" class="fchip" data-flow="' + esc(f.id) + '" aria-pressed="' + (S.flow === f.id) + '" title="' + esc(f.about) + '">' +
          '<i style="background:var(--f' + f.color + ')"></i>' + esc(f.name) + (s ? '<span class="pill ' + (s === "direct" ? "info" : "warn") + '">' + esc(t("flow_" + s)) + "</span>" : "") + "</button>";
      }).join("");
      root.querySelector(".slegend").innerHTML = (ov && S.overlay ?
        '<span><i class="sw-n s-chg"></i>' + esc(t("st_chg")) + '</span><span><i class="sw-n s-new"></i>' + esc(t("st_new")) +
        '</span><span><i class="sw-n s-aff"></i>' + esc(t("st_aff")) + '</span><span><i class="sw-n s-del"></i>' + esc(t("st_del")) +
        '</span><span><i class="sw-l"></i>' + esc(t("edge_new")) + "</span>" : "") +
        (model.edges.some(function (e) { return e.k === "miss"; }) ? '<span><i class="sw-l miss"></i>' + esc(t("edge_miss")) + "</span>" : "") +
        '<span><i class="sw-d"></i>' + esc(t("legend_stale")) + "</span>";
    }
    function flowStatus(f) {
      if (!ov || !S.overlay) return "";
      var ss = [];
      f.chains.forEach(function (c) { c.forEach(function (m) { ss.push(ov.status[m]); }); });
      if (ss.some(function (s) { return s === "chg" || s === "new" || s === "del"; })) return "direct";
      return ss.indexOf("aff") >= 0 ? "indirect" : "";
    }
    function sync() {
      root.querySelectorAll('[data-ctl="view"] button').forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-v") === S.view)); });
      root.querySelectorAll('[data-ctl="overlay"] button').forEach(function (b) { b.setAttribute("aria-pressed", String((b.getAttribute("data-v") === "on") === S.overlay)); });
      var fc = root.querySelector('input[data-ctl="flows"]'), dc = root.querySelector('input[data-ctl="deps"]');
      if (fc) fc.checked = S.flows;
      if (dc) dc.checked = S.deps;
    }
    function panel() {
      var ctx = { model: model, S: S, t: t, lang: lang, stOf: stOf, groupSub: groupSub, flowStatus: flowStatus, vis: vis, extras: opts.extras || {} };
      if (!S.sel) side.innerHTML = opts.defaultPanel(ctx);
      else if (S.view === "module") side.innerHTML = modulePanel(ctx, S.sel);
      else side.innerHTML = groupPanel(ctx, S.sel);
    }
    function select(id) {
      S.sel = id;
      highlight(); panel();
      if (id && window.matchMedia && matchMedia("(max-width: 1040px)").matches) {
        side.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      }
    }
    function go(id) {
      if (!model.modules[id]) return;
      if (!vis[id]) { S.overlay = true; }
      if (S.view !== "module" || !vis[id]) { S.view = "module"; S.sel = id; S.hover = null; render(); }
      else select(id);
    }
    function toggleFlow(id) {
      S.flow = S.flow === id ? null : id;
      if (!S.flows) { S.flows = true; svg.classList.add("show-flows"); sync(); }
      legend(); highlight(); panel();
    }

    svg.addEventListener("click", function (e) { if (!e.target.closest(".node")) select(null); });
    root.addEventListener("click", function (e) {
      var b = e.target.closest("[data-flow],[data-go],[data-grp],[data-back],[data-ctl] button");
      if (!b || !root.contains(b)) return;
      if (b.hasAttribute("data-flow")) return toggleFlow(b.getAttribute("data-flow"));
      if (b.hasAttribute("data-go")) return go(b.getAttribute("data-go"));
      if (b.hasAttribute("data-grp")) { S.view = "domain"; S.sel = b.getAttribute("data-grp"); S.hover = null; return render(); }
      if (b.hasAttribute("data-back")) return select(null);
      var ctl = b.parentNode.getAttribute("data-ctl"), v = b.getAttribute("data-v");
      if (ctl === "view" && v !== S.view) {
        S.view = v;
        if (S.sel) S.sel = v === "domain" ? (groupOf[S.sel] || null) : null;
        S.hover = null; render();
      } else if (ctl === "overlay") {
        S.overlay = v === "on";
        if (S.sel && S.view === "module" && !visibleIds(model, S.overlay)[S.sel]) S.sel = null;
        S.hover = null; render();
      }
    });
    root.addEventListener("change", function (e) {
      var ctl = e.target.getAttribute("data-ctl");
      if (ctl === "flows") { S.flows = e.target.checked; if (!S.flows) S.flow = null; render(); }
      if (ctl === "deps") { S.deps = e.target.checked; svg.classList.toggle("show-deps", S.deps); }
    });

    render();
    return { state: S, go: go, render: render };
  }

  /* ------------------------------------------------------------------ panel pages */

  var PROV = function (t, k) { return '<span class="prov ' + k + '">' + esc(t("prov_" + k)) + "</span>"; };
  function pill(t, st) { return st ? '<span class="pill ' + st + '">' + esc(t("st_" + st)) + "</span>" : ""; }
  function mchip(ctx, id) {
    var m = ctx.model.modules[id], st = ctx.S.overlay && ctx.model.overlay ? ctx.model.overlay.status[id] : null;
    if (!m) return "";
    var label = m.kind === "external" ? m.label : m.path.replace(/\.(py|ts|tsx|js|jsx)$/, "");
    return '<button type="button" class="mchip" data-go="' + esc(id) + '">' + (st ? '<i class="dot ' + st + '"></i>' : "") + esc(label) + "</button>";
  }
  function flowChip(ctx, f) {
    return '<button type="button" class="fchip" data-flow="' + esc(f.id) + '" aria-pressed="' + (ctx.S.flow === f.id) + '"><i style="background:var(--f' + f.color + ')"></i>' + esc(f.name) + "</button>";
  }
  function back(ctx) { return '<button type="button" class="back" data-back>← ' + esc(ctx.t("back")) + "</button>"; }

  function reasonText(ctx, r) {
    var t = ctx.t, mod = ctx.model.modules[r.module];
    var where = mod ? mod.path : r.module;
    if (r.reason === "reads-config") return t("why_config", { key: r.names[0], old: r.old == null ? "—" : r.old, new: r["new"] == null ? "—" : r["new"] });
    if (r.reason === "uses-changed-api") return t("why_api", { names: r.names.join(", "), module: where });
    if (r.reason === "uses-modified") return t("why_modified", { names: r.names.join(", "), module: where });
    return t("why_imports", { module: where });
  }
  function symChange(ctx, c) {
    var t = ctx.t, cls = { added: "new", removed: "del", renamed: "chg", signature: "aff", modified: "chg" }[c.change];
    var extra = [];
    if (c.from) extra.push(t("sym_from", { name: c.from }));
    if (c.change === "signature" && c.sig) extra.push((c.sig[0] || "") + " → " + (c.sig[1] || ""));
    if (c.complexity && c.complexity[0] != null && c.complexity[1] != null && c.complexity[0] !== c.complexity[1]) {
      extra.push(t("complexity_change", { a: c.complexity[0], b: c.complexity[1] }));
    } else if (c.complexity && c.complexity[0] == null && c.complexity[1] != null) {
      extra.push(t("complexity", { n: c.complexity[1] }));
    }
    return '<li><code>' + esc(c.name) + '</code><span class="pill ' + cls + '">' + esc(t("sym_" + c.change)) + '</span><span class="small">' + esc(extra.join(" · ")) + "</span></li>";
  }

  function modulePanel(ctx, id) {
    var t = ctx.t, lang = ctx.lang, model = ctx.model, m = model.modules[id], g = null;
    model.groups.forEach(function (x) { if (x.id === m.group) g = x; });
    var layer = g ? (model.layers.filter(function (l) { return l.id === g.layer; })[0] || {}).name : "";
    var st = ctx.S.overlay && model.overlay ? model.overlay.status[id] : null;
    var det = model.overlay && model.overlay.details[id];
    var flows = model.flows.filter(function (f) { return f.chains.some(function (c) { return c.indexOf(id) >= 0; }); });
    var h = back(ctx) + '<div class="ph"><span class="label">' + esc((g ? g.name : "") + (layer ? " · " + layer : "")) + "</span>" +
      '<h3 class="mono-title">' + esc(m.path) + '</h3><div class="chips">' + pill(t, st) +
      (m.owners.length ? '<span class="small">' + esc(m.owners.join(" ")) + "</span>" : "") + "</div></div>";

    if (st) {
      var body = "";
      if (st === "chg" || st === "new") {
        body += "<p>" + esc(t(st === "new" ? "ov_new" : "ov_changed", { a: det ? det.added : 0, d: det ? det.deleted : 0 })) + "</p>";
        if (det && det.config && det.config.length) {
          body += "<ul>" + det.config.map(function (c) { return "<li><code>" + esc(c.key) + "</code> " + esc((c.old == null ? "—" : c.old) + " → " + (c["new"] == null ? "—" : c["new"])) + " · " + esc(t("n_readers", { n: c.readers.length })) + "</li>"; }).join("") + "</ul>";
        }
        if (st === "chg") body += '<p class="small">' + esc(t("ov_rewrite")) + "</p>";
      } else if (st === "del") {
        body += "<p>" + esc(t("ov_deleted")) + "</p>";
      } else if (st === "aff" && det) {
        body += "<ul>" + det.reasons.map(function (r) { return "<li>" + esc(reasonText(ctx, r)) + "</li>"; }).join("") + "</ul>";
      }
      h += '<div class="brbox s-' + st + '"><span class="label">' + esc(t("this_branch")) + "</span>" + body + "</div>";
    }
    var notes = (ctx.extras.moduleNotes || {})[id];
    if (notes && notes.length) {
      h += '<div class="brbox"><div class="bh"><span class="label">' + esc(t("review_notes")) + "</span>" + PROV(t, "ai") + "</div><ul>" +
        notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul></div>";
    }

    if (m.kind !== "external" || m.about) {
      var fresh = m.fresh === "current" ? t("fresh_current", { rev: (m.fresh_rev || "").slice(0, 7) }) :
                  m.fresh === "stale" ? '<span class="warnt">' + esc(t("fresh_stale")) + "</span> " + esc(t("fresh_stale_detail", { rev: (m.fresh_rev || "?").slice(0, 7) })) :
                  m.fresh === "pending" ? '<span class="warnt">' + esc(t("fresh_pending")) + "</span>" : esc(t("fresh_missing"));
      h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("purpose")) + "</span>" + PROV(t, "ai") + "</div>" +
        (m.about ? "<p>" + esc(m.about) + "</p>" : '<p class="small">' + esc(t("no_page")) + "</p>") +
        '<p class="ref">' + (m.refs ? esc(t("based_on")) + " <code>" + esc(m.refs) + "</code> · " : "") + (m.fresh === "current" ? esc(fresh) : fresh) + "</p>" +
        (m.pending_about ? '<div class="pending-about"><span class="label">' + esc(t("pending_rewrite")) + "</span><p>" + esc(m.pending_about) + "</p></div>" : "") + "</div>";
    }

    var facts = m.kind === "external" ? [[t("version"), m.version || "—"], [t("callers"), m.callers.length]] :
      [[t("loc"), fmt(m.loc, lang)], [t("coverage"), m.coverage == null ? "—" : m.coverage + "%"],
       [t("churn"), t("n_times", { n: m.churn })], [t("callers"), m.callers.length]];
    h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("facts")) + "</span>" + PROV(t, "fact") + '</div><div class="facts">' +
      facts.map(function (f) { return '<div><span class="small">' + esc(f[0]) + "</span><b>" + esc(f[1]) + "</b></div>"; }).join("") + "</div></div>";

    if (det && det.symbols && det.symbols.length && (st === "chg" || st === "new")) {
      h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("symbols_changed")) + "</span>" + PROV(t, "fact") + '</div><ul class="syms">' +
        det.symbols.slice(0, 20).map(function (c) { return symChange(ctx, c); }).join("") + "</ul></div>";
    } else if (m.symbols.length) {
      var top = m.symbols.filter(function (s) { return s.kind !== "class"; }).slice().sort(function (a, b) { return (b.complexity || 0) - (a.complexity || 0); }).slice(0, 10);
      if (top.length) {
        h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("symbols")) + "</span>" + PROV(t, "fact") + '</div><ul class="syms">' +
          top.map(function (s) { return "<li><code>" + esc(s.name) + '</code><span class="small">' + esc((s.complexity ? t("complexity", { n: s.complexity }) : "") + (s.file && s.file !== m.path ? " · " + s.file : "")) + "</span></li>"; }).join("") + "</ul></div>";
      }
    }
    if (m.config_reads.length) {
      h += '<div class="blk"><span class="label">' + esc(t("reads_config")) + '</span><div class="chips">' + m.config_reads.map(function (k) { return "<code>" + esc(k) + "</code>"; }).join(" ") + "</div></div>";
    }
    if (m.pins.length) {
      var checks = (ctx.extras.pinChecks || {})[id] || [];
      h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("pins")) + "</span>" + PROV(t, "pin") + "</div>" + m.pins.map(function (p) {
        var c = ctx.S.overlay ? checks.filter(function (x) { return x.pin === p.text || (x.pin && p.text.indexOf(x.pin) === 0); })[0] : null;
        return '<div class="pinx"><p>' + esc(p.text) + '</p><span class="small">' + esc([p.by, p.date].filter(Boolean).join(" · ")) + "</span>" +
          (c ? '<span class="chk ' + (c.ok ? "ok" : "bad") + '">' + (c.ok ? "✓ " : "✗ ") + esc(c.note || "") + "</span>" : "") + "</div>";
      }).join("") + "</div>";
    }
    if (m.callers.length) h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("called_by")) + "</span>" + PROV(t, "fact") + '</div><div class="chips">' + m.callers.map(function (x) { return mchip(ctx, x); }).join("") + "</div></div>";
    if (m.deps.length) h += '<div class="blk"><div class="bh"><span class="label">' + esc(t("depends_on")) + "</span>" + PROV(t, "fact") + '</div><div class="chips">' + m.deps.map(function (x) { return mchip(ctx, x); }).join("") + "</div></div>";
    if (flows.length) h += '<div class="blk"><span class="label">' + esc(t("flows_through")) + '</span><div class="chips">' + flows.map(function (f) { return flowChip(ctx, f); }).join("") + "</div></div>";
    return h;
  }

  function groupPanel(ctx, id) {
    var t = ctx.t, model = ctx.model, g = model.groups.filter(function (x) { return x.id === id; })[0];
    if (!g) return back(ctx);
    var layer = (model.layers.filter(function (l) { return l.id === g.layer; })[0] || {}).name || "";
    var ids = g.modules.filter(function (m) { return ctx.vis[m]; });
    var st = ctx.stOf(id);
    var flows = model.flows.filter(function (f) { return f.chains.some(function (c) { return c.some(function (m) { return g.modules.indexOf(m) >= 0; }); }); });
    return back(ctx) + '<div class="ph"><span class="label">' + esc(layer) + "</span><h3>" + esc(g.name) + "</h3>" +
      (g.include.length ? '<p class="small mono">' + esc(g.include.join(" · ")) + "</p>" : "") + "</div>" +
      (st ? '<div class="brbox s-' + st + '"><span class="label">' + esc(t("this_branch")) + "</span><p>" + esc(ctx.groupSub(g)) + "</p></div>" : "") +
      (g.about ? '<div class="blk"><div class="bh"><span class="label">' + esc(t("purpose")) + "</span>" + PROV(t, "ai") + "</div><p>" + esc(g.about) + "</p></div>" : "") +
      '<div class="blk"><div class="bh"><span class="label">' + esc(t("modules")) + "</span>" + PROV(t, "fact") + '</div><div class="chips">' + ids.map(function (m) { return mchip(ctx, m); }).join("") + "</div></div>" +
      (flows.length ? '<div class="blk"><span class="label">' + esc(t("flows_through")) + '</span><div class="chips">' + flows.map(function (f) { return flowChip(ctx, f); }).join("") + "</div></div>" : "");
  }

  var api = { create: create, layout: layout, subText: subText, visibleIds: visibleIds, esc: esc, fmt: fmt, mchip: mchip, flowChip: flowChip, PROV: PROV, textWidth: textWidth };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  return api;
})();
