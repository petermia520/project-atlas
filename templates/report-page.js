/* Branch review report. Data: render.build_report_page(); judgement fields come from report.json. */
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("atlas-data").textContent);
  var R = D.report || {};
  var t = AtlasI18n.t(D.lang), esc = AtlasMap.esc, fmt = AtlasMap.fmt, lang = D.lang;
  var OV = D.map.overlay;
  var KEY = "atlas:" + D.head.sha;
  var store = {
    get: function (k, d) { try { var v = JSON.parse(localStorage.getItem(KEY + ":" + k)); return v == null ? d : v; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(KEY + ":" + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };
  function when(iso) { return (iso || "").slice(0, 16).replace("T", " "); }
  function short(sha) { return (sha || "").slice(0, 7); }
  function dur(s) {
    if (!s) return "—";
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h ? t("dur_hm", { h: h, m: m }) : t("dur_m", { m: m });
  }
  function compact(n) {
    if (!n) return "0";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
    return String(n);
  }
  var SEV_PILL = { crit: "crit", warn: "warn", info: "info", ok: "ok" };
  var AGENT_NAMES = { "claude-code": "Claude Code", pi: "pi", omp: "oh-my-pi" };
  var sections = [];

  /* ---------------------------------------------------------------- header + strip */
  sections.push(
    '<header><div class="meta"><span class="mono">' + esc(D.repo) + "</span><span>·</span><span>" +
    esc(t("generated_at", { when: when(D.generated_at) })) + "</span>" +
    (R.verdict ? "" : '<span class="pill warn">' + esc(t("no_judgement")) + "</span>") + "</div>" +
    '<div class="branchline"><span>' + esc(D.branch || short(D.head.sha)) + '</span><span class="small">→</span><span class="base">' +
    esc(D.base.ref) + "</span></div>" +
    (D.task ? '<div class="task"><span class="label">' + esc(t("task")) + "</span><p>" + esc(D.task) + "</p></div>" : "") + "</header>");

  var st = D.stats, v = R.verdict || {};
  var allAdded = 0, allDeleted = 0;
  Object.keys(D.lines.by_kind).forEach(function (k) { if (k !== "atlas") { allAdded += D.lines.by_kind[k].added; allDeleted += D.lines.by_kind[k].deleted; } });
  sections.push('<div class="panel strip" aria-label="' + esc(t("summary")) + '">' +
    "<div><span class=\"label\">" + esc(t("verdict")) + '</span><span class="verdict ' + esc(v.level || "") + '"><span class="vdot"></span>' +
      esc(v.headline || t("verdict_none")) + '</span><span class="small">' + esc(v.summary || "") + "</span></div>" +
    '<div><span class="label">' + esc(t("source_code")) + '</span><span class="big"><span class="plus">+' + fmt(st.source.added, lang) + '</span> <span class="minus">−' +
      fmt(st.source.deleted, lang) + '</span></span><span class="small">' + esc(t("all_changes", { a: fmt(allAdded, lang), d: fmt(allDeleted, lang), n: st.files })) + "</span></div>" +
    '<div><span class="label">' + esc(t("commits")) + '</span><span class="big">' + st.commits + '</span><span class="small">' + esc(t("n_sessions", { n: st.sessions })) + "</span></div>" +
    '<div><span class="label">' + esc(t("tests")) + '</span><span class="big">+' + st.tests_added + '</span><span class="small">' +
      esc(st.skipped.length ? t("n_skipped", { n: st.skipped.length }) : t("tests_removed", { n: st.tests_removed })) + "</span></div>" +
    '<div><span class="label">' + esc(t("human_input")) + '</span><span class="big">' + st.human_messages + '</span><span class="small">' +
      esc(t("human_input_sub")) + "</span></div></div>");

  /* ---------------------------------------------------------------- attention */
  var ack = store.get("ack", []);
  if ((R.attention || []).length) {
    sections.push('<section aria-labelledby="h-attn"><h2 id="h-attn">' + esc(t("attention")) + ' <span class="sub">' + esc(t("attention_sub")) + '</span></h2><ul class="attn" id="attn">' +
      R.attention.map(function (a, i) {
        var id = a.id || "a" + i, done = ack.indexOf(id) >= 0;
        return '<li class="' + esc(a.severity) + (done ? " done" : "") + '" data-ack="' + esc(id) + '"><span class="pill ' + SEV_PILL[a.severity] + '">' + esc(a.tag || t("sev_" + a.severity)) + "</span>" +
          "<div><h3>" + esc(a.title) + "</h3>" + (a.detail ? "<p>" + esc(a.detail) + "</p>" : "") + "</div>" +
          '<div><button class="chip" type="button" aria-pressed="' + done + '">' + esc(done ? t("acked") : t("ack")) + "</button></div>" +
          (a.where ? '<span class="where small mono">' + esc(a.where) + "</span>" : "") + "</li>";
      }).join("") + "</ul></section>");
  }

  /* ---------------------------------------------------------------- impact map */
  sections.push('<section aria-labelledby="h-map"><h2 id="h-map">' + esc(t("impact_title")) + ' <span class="sub">' + esc(t("impact_sub")) + "</span></h2>" +
    '<div id="atlas-map"></div>' + ((R.structure || []).length ? '<div class="panel" id="structure"><ul class="finds">' + R.structure.map(function (s) {
      return '<li><div class="hd"><span class="pill ' + SEV_PILL[s.severity] + '">' + esc(s.tag || t("sev_" + s.severity)) + "</span><span>" + esc(s.title) + "</span>" +
        (s.module ? AtlasMap.mchip({ model: D.map, S: { overlay: true } }, s.module) : "") + "</div>" + (s.detail ? "<p>" + esc(s.detail) + "</p>" : "") + "</li>";
    }).join("") + "</ul></div>" : "") + "</section>");

  /* ---------------------------------------------------------------- scope */
  var sc = R.scope;
  if (sc && ((sc.requested || []).length || (sc.extra || []).length || (sc.missing || []).length)) {
    var MK = { done: "✓", partial: "◐", missing: "✗" };
    var col = function (title, items, mk) {
      return '<div><span class="label">' + esc(title) + "</span><ul>" + (items || []).map(function (it) {
        var s = mk || it.status;
        return '<li><span class="mk ' + esc(s) + '">' + (MK[s] || "+") + "</span><span>" + esc(it.text || it) + "</span></li>";
      }).join("") + ((items || []).length ? "" : '<li><span></span><span class="small">' + esc(t("none")) + "</span></li>") + "</ul></div>";
    };
    sections.push('<section aria-labelledby="h-scope"><h2 id="h-scope">' + esc(t("scope_title")) + "</h2>" + '<div class="panel scope">' +
      col(t("scope_requested"), sc.requested) + col(t("scope_extra"), sc.extra, "extra") + col(t("scope_missing"), sc.missing, "missing") + "</div></section>");
  }

  /* ---------------------------------------------------------------- code vs tests */
  var KIND_ORDER = ["source", "test", "fixture", "config", "manifest", "doc", "example", "ci", "generated", "other"];
  var kinds = KIND_ORDER.filter(function (k) { return D.lines.by_kind[k] && D.lines.by_kind[k].added; });
  var totalAdded = kinds.reduce(function (a, k) { return a + D.lines.by_kind[k].added; }, 0);
  var bar = function (parts, total) {
    return '<div class="stack" role="img" aria-label="' + esc(parts.map(function (p) { return p[1] + " " + p[2]; }).join(", ")) + '">' +
      parts.map(function (p) { return '<i class="c-' + p[0] + '" style="width:' + (100 * p[2] / Math.max(total, 1)).toFixed(1) + '%"></i>'; }).join("") + "</div>" +
      '<div class="keys">' + parts.map(function (p) { return '<span><i class="c-' + p[0] + '"></i>' + esc(p[1]) + " <b>" + fmt(p[2], lang) + "</b> " + Math.round(100 * p[2] / Math.max(total, 1)) + "%</span>"; }).join("") + "</div>";
  };
  if (totalAdded) {
    var sa = D.lines.source_added || {}, srcTotal = Object.keys(sa).reduce(function (a, k) { return a + sa[k]; }, 0);
    var testAdded = (D.lines.by_kind.test || {}).added || 0, srcAdded = (D.lines.by_kind.source || {}).added || 0;
    var ratio = srcAdded ? testAdded / srcAdded : null;
    var base = D.baseline && D.baseline.ratio;
    var tq = R.tests || {}, mut = R.mutation;
    sections.push('<section aria-labelledby="h-mix"><h2 id="h-mix">' + esc(t("mix_title")) + ' <span class="sub">' + esc(t("mix_sub", { n: fmt(totalAdded, lang) })) + "</span></h2>" +
      '<div class="two"><div class="panel"><div class="mix"><div style="display:grid;gap:8px"><span class="label">' + esc(t("added_by_kind", { n: fmt(totalAdded, lang) })) + "</span>" +
      bar(kinds.map(function (k) { return [k, t("kind_" + k), D.lines.by_kind[k].added]; }), totalAdded) + "</div>" +
      (srcTotal ? '<div style="display:grid;gap:8px"><span class="label">' + esc(t("source_breakdown", { n: fmt(srcTotal, lang) })) + "</span>" +
        bar(["logic", "comment", "docstring", "import", "blank"].filter(function (k) { return sa[k]; }).map(function (k) { return [k, t("line_" + k), sa[k]]; }), srcTotal) + "</div>" : "") +
      '</div><div class="ratio"><div><span class="label">' + esc(t("ratio_test_source")) + '</span><span class="big"' + (ratio != null && base != null && ratio > 2 * base ? ' style="color:var(--warn)"' : "") + ">" +
        (ratio == null ? "—" : ratio.toFixed(1) + " : 1") + '</span><span class="small">' + esc(t("ratio_detail", { a: fmt(testAdded, lang), b: fmt(srcAdded, lang) })) + "</span></div>" +
      '<div><span class="label">' + esc(t("ratio_baseline")) + '</span><span class="big">' + (base == null ? "—" : base.toFixed(1) + " : 1") + '</span><span class="small">' +
        esc(D.baseline ? t("baseline_detail", { days: D.baseline.days, n: D.baseline.commits }) : t("baseline_missing")) + "</span></div>" +
      (mut ? '<div><span class="label">' + esc(t("mutation")) + '</span><span class="big">' + mut.killed + " / " + mut.total + '</span><span class="small">' + esc(mut.note || t("mutation_detail")) + "</span></div>"
           : '<div><span class="label">' + esc(t("tests_added_label")) + '</span><span class="big">+' + st.tests_added + '</span><span class="small">' + esc(t("tests_removed", { n: st.tests_removed })) + "</span></div>") +
      "</div></div>" +
      '<div class="panel">' + ((tq.classification || []).length ?
        '<div class="bh" style="padding:12px 16px 0"><span class="label">' + esc(t("tests_what")) + "</span>" + AtlasMap.PROV(t, "ai") + '</div><div class="tbl-wrap"><table><thead><tr><th>' + esc(t("category")) + "</th><th>" + esc(t("count")) + "</th><th>" + esc(t("advice")) + "</th></tr></thead><tbody>" +
        tq.classification.map(function (c) {
          return '<tr><td><span class="pill ' + (SEV_PILL[c.severity] || "info") + '">' + esc(c.label) + "</span> " + esc(c.detail || "") + '</td><td class="num">' + esc(c.count) + '</td><td class="why">' + esc(c.advice || "") + "</td></tr>";
        }).join("") + "</tbody></table></div>" + (tq.note ? '<p class="small" style="margin:0;padding:10px 16px 14px">' + esc(tq.note) + "</p>" : "")
        : '<p class="empty">' + esc(t("tests_unclassified")) + "</p>") +
      (st.skipped.length ? '<div class="blk" style="padding:12px 16px 14px"><span class="label">' + esc(t("skipped_added")) + '</span><ul class="syms">' + st.skipped.map(function (s) {
        return '<li><code>' + esc(s.path + ":" + s.line) + '</code><span class="small">' + esc(s.text) + "</span></li>";
      }).join("") + "</ul></div>" : "") + "</div></div></section>");
  }

  /* ---------------------------------------------------------------- files */
  sections.push('<section aria-labelledby="h-files"><div class="toolbar"><h2 id="h-files">' + esc(t("files_title")) + ' <span class="sub">' +
    esc((R.review_order || []).length ? t("files_sub_order") : t("files_sub")) + '</span></h2><div class="ctl"><span class="progress" id="prog"></span>' +
    '<div class="seg" role="group" id="file-filter"><button type="button" data-f="all" aria-pressed="true">' + esc(t("f_all")) + '</button><button type="button" data-f="source" aria-pressed="false">' +
    esc(t("kind_source")) + '</button><button type="button" data-f="test" aria-pressed="false">' + esc(t("kind_test")) + '</button><button type="button" data-f="todo" aria-pressed="false">' + esc(t("f_todo")) + "</button></div></div></div>" +
    '<div class="panel tbl-wrap"><table><thead><tr><th>' + esc(t("order")) + "</th><th>" + esc(t("file")) + "</th><th>" + esc(t("change")) + "</th><th></th><th>" + esc(t("kind")) + "</th><th>" + esc(t("note")) + "</th><th>" + esc(t("reviewed")) + '</th></tr></thead><tbody id="files"></tbody></table></div></section>');

  /* ---------------------------------------------------------------- timeline + verification */
  var S = D.sessions || { sessions: [], trailers: [], totals: {} };
  function timeline() {
    var rows = [];
    if ((R.timeline || []).length) {
      var cur = null;
      R.timeline.forEach(function (s) {
        if (s.session !== cur) { cur = s.session; rows.push({ head: s.session_label || (s.session ? t("session") + " " + String(s.session).slice(0, 8) : t("other_steps")) }); }
        rows.push({ text: s.text, kind: s.kind || "step", meta: s.meta || [] });
      });
    } else {
      var used = {};
      S.sessions.forEach(function (s) {
        rows.push({ head: t("session") + " " + String(s.id).slice(0, 8) + " · " + (AGENT_NAMES[s.agent] || s.agent || "") + " · " + when(s.start).slice(5) + " – " + when(s.end).slice(11) + " · " + dur(s.duration_s) +
          (s.matched_by === "time" ? " · " + t("matched_time") : "") });
        var items = [];
        if (s.task) items.push({ ts: s.start, text: s.task.split("\n")[0].slice(0, 200), kind: "step", meta: [t("first_prompt")] });
        (s.human_messages || []).forEach(function (m) { items.push({ ts: m.ts, text: m.text, kind: "human", meta: [t("human_msg")] }); });
        var a = Date.parse(s.start), b = Date.parse(s.end) + 120000;
        D.commits.forEach(function (c) {
          var ct = Date.parse(c.date);
          if (!used[c.sha] && ct >= a && ct <= b) { used[c.sha] = true; items.push({ ts: new Date(ct).toISOString(), text: c.subject, kind: "commit", meta: [short(c.sha)] }); }
        });
        if (s.interrupts) items.push({ ts: s.end, text: t("interrupts", { n: s.interrupts }), kind: "interrupt", meta: [] });
        items.push({ ts: s.end, text: t("session_stats", { n: s.tool_calls, f: (s.files_touched || []).length }), kind: "step", meta: [s.source === "transcript" ? t("src_transcript") : t("src_" + s.source)] });
        items.sort(function (a, b) { return (a.ts || "") < (b.ts || "") ? -1 : 1; }).forEach(function (i) { rows.push(i); });
      });
      var rest = D.commits.filter(function (c) { return !used[c.sha]; });
      if (rest.length) {
        rows.push({ head: S.sessions.length ? t("other_commits") : t("commits") });
        rest.forEach(function (c) { rows.push({ text: c.subject, kind: "commit", meta: [short(c.sha), c.author, when(c.date)] }); });
      }
    }
    if (!rows.length) return '<p class="empty">' + esc(t("no_sessions")) + "</p>";
    return '<ol class="tl">' + rows.map(function (r, i) {
      if (r.head) return '<li class="sess">' + esc(r.head) + "</li>";
      var last = !rows[i + 1] || rows[i + 1].head;
      return '<li class="step ' + esc(r.kind) + (last ? " last" : "") + '"><span class="node-dot"></span><div><div class="t">' + esc(r.text) + '</div><div class="m">' +
        r.meta.filter(Boolean).map(function (m) { return "<span>" + esc(m) + "</span>"; }).join("") + "</div></div></li>";
    }).join("") + "</ol>";
  }
  var checks = D.checks || [];
  var tok = S.totals || {};
  sections.push('<div class="two"><section aria-labelledby="h-tl"><h2 id="h-tl">' + esc(t("timeline_title")) + ' <span class="sub">' +
    esc(S.missing && S.missing.length ? t("sessions_missing", { n: S.missing.length }) : t("timeline_sub")) + '</span></h2><div class="panel">' + timeline() + "</div></section>" +
    '<section aria-labelledby="h-ver"><h2 id="h-ver">' + esc(t("verification")) + '</h2><div class="panel">' +
    (checks.length ? '<ul class="checks">' + checks.map(function (c) {
      return '<li><span class="n">' + (c.url ? '<a href="' + esc(c.url) + '" target="_blank" rel="noopener">' + esc(c.name) + "</a>" : esc(c.name)) + '</span><span class="pill ' + esc(c.status) + '">' + esc(t("check_" + c.status)) + "</span>" +
        (c.summary || c.workflow ? '<span class="d">' + esc(c.summary || c.workflow) + "</span>" : "") + "</li>";
    }).join("") + "</ul>" : '<p class="empty">' + esc(t("no_checks")) + (D.checks_source ? " (" + esc(D.checks_source) + ")" : "") + "</p>") +
    '<div class="effort"><div><span class="label">' + esc(t("active_time")) + '</span><div class="big">' + esc(dur(tok.duration_s)) + "</div></div>" +
    '<div><span class="label">' + esc(t("tool_calls")) + '</span><div class="big">' + fmt(tok.tool_calls || 0, lang) + "</div></div>" +
    '<div><span class="label">' + esc(t("tokens_in")) + '</span><div class="big">' + compact((tok.input_tokens || 0) + (tok.cache_read_input_tokens || 0) + (tok.cache_creation_input_tokens || 0)) + "</div></div>" +
    '<div><span class="label">' + esc(t("tokens_out")) + '</span><div class="big">' + compact(tok.output_tokens || 0) + "</div></div></div>" +
    (tok.cost_usd ? '<p class="small" style="margin:0;padding:0 16px 14px">' + esc(t("cost_reported", { usd: tok.cost_usd.toFixed(2) })) + "</p>" : "") +
    "</div></section></div>");

  /* ---------------------------------------------------------------- decisions */
  var decisions = (R.decisions || []).map(function (d) { return { title: d.title, why: d.why, alt: d.alternatives, src: "ai" }; });
  S.trailers.forEach(function (tr) {
    var k = tr.key.toLowerCase();
    if (k === "agent-decision" || k === "agent-assumption") decisions.push({ title: tr.value, why: "", alt: "", src: k === "agent-decision" ? "decision" : "assumption", sha: tr.sha });
  });
  if (decisions.length) {
    sections.push('<section aria-labelledby="h-dec"><h2 id="h-dec">' + esc(t("decisions_title")) + ' <span class="sub">' + esc(t("decisions_sub")) + '</span></h2><div class="dec">' +
      decisions.map(function (d) {
        return '<article class="panel"><div class="bh">' + (d.src === "ai" ? AtlasMap.PROV(t, "ai") : '<span class="pill ' + (d.src === "assumption" ? "warn" : "info") + '">' + esc(t("trailer_" + d.src)) + "</span>") +
          (d.sha ? '<span class="small mono">' + esc(short(d.sha)) + "</span>" : "") + "</div><h3>" + esc(d.title) + "</h3>" + (d.why ? "<p>" + esc(d.why) + "</p>" : "") +
          (d.alt ? '<p class="small mono">' + esc(t("alternatives")) + ": " + esc(Array.isArray(d.alt) ? d.alt.join("; ") : d.alt) + "</p>" : "") + "</article>";
      }).join("") + "</div></section>");
  }

  /* ---------------------------------------------------------------- footer */
  var srcs = {};
  S.sessions.forEach(function (s) { srcs[s.source] = true; });
  sections.push("<footer><span>" + esc(t("sources", { range: short(D.merge_base) + ".." + short(D.head.sha) })) + "</span>" +
    ((S.agents || []).length ? "<span>" + esc(t("agents_seen", { list: S.agents.map(function (a) { return AGENT_NAMES[a] || a; }).join(", ") })) + "</span>" : "") +
    "<span>" + esc(t("session_sources", { list: Object.keys(srcs).map(function (k) { return t("src_" + k); }).join(", ") || t("none") })) + "</span>" +
    "<span>" + esc(t("local_ack")) + "</span><span>" + esc(D.tool) + "</span>" +
    (D.warnings.length ? "<span>" + esc(t("n_warnings", { n: D.warnings.length })) + "</span>" : "") + "</footer>");

  document.getElementById("app").innerHTML = sections.join("");

  /* ---------------------------------------------------------------- behaviour */
  document.querySelectorAll("#attn li").forEach(function (li) {
    var id = li.getAttribute("data-ack"), b = li.querySelector("button");
    b.addEventListener("click", function () {
      var i = ack.indexOf(id);
      if (i >= 0) ack.splice(i, 1); else ack.push(id);
      store.set("ack", ack);
      var on = ack.indexOf(id) >= 0;
      li.classList.toggle("done", on);
      b.setAttribute("aria-pressed", String(on));
      b.textContent = on ? t("acked") : t("ack");
    });
  });

  var seen = store.get("seen", []), filter = "all";
  var maxChurn = Math.max.apply(null, D.files.map(function (f) { return f.added + f.deleted; }).concat([1]));
  function renderFiles() {
    var rows = D.files.filter(function (f) {
      if (filter === "source") return f.kind === "source" || f.kind === "config";
      if (filter === "test") return f.kind === "test" || f.kind === "fixture";
      if (filter === "todo") return seen.indexOf(f.path) < 0;
      return true;
    });
    document.getElementById("files").innerHTML = rows.map(function (f) {
      var i = f.path.lastIndexOf("/"), tot = f.added + f.deleted, w = Math.max(4, 90 * tot / maxChurn);
      var reviewed = seen.indexOf(f.path) >= 0;
      return '<tr class="' + (reviewed ? "reviewed" : "") + '"><td class="order">' + (f.order ? String(f.order).padStart(2, "0") : "") + "</td>" +
        '<td class="path"><span class="dir">' + esc(f.path.slice(0, i + 1)) + "</span>" + esc(f.path.slice(i + 1)) +
        (f.old_path && f.old_path !== f.path ? '<br><span class="small">' + esc(t("renamed_from", { p: f.old_path })) + "</span>" : "") + "</td>" +
        '<td class="num">' + (f.binary ? esc(t("binary")) : '<span class="plus">+' + f.added + '</span> <span class="minus">−' + f.deleted + "</span>") + "</td>" +
        '<td><span class="bar" style="width:' + w + 'px"><i class="a" style="width:' + (100 * f.added / Math.max(tot, 1)) + '%"></i><i class="d" style="width:' + (100 * f.deleted / Math.max(tot, 1)) + '%"></i></span></td>' +
        '<td><span class="pill ' + (f.status === "D" ? "del" : f.status === "A" ? "new" : "skip") + '">' + esc(t("kind_" + f.kind)) + "</span>" +
        (f.status_mod === "aff" ? "" : "") + "</td>" +
        '<td class="why">' + esc(f.note || "") + "</td>" +
        '<td><input type="checkbox" data-p="' + esc(f.path) + '" aria-label="' + esc(t("reviewed") + " " + f.path) + '"' + (reviewed ? " checked" : "") + "></td></tr>";
    }).join("") || '<tr><td colspan="7" class="why">' + esc(t("no_files")) + "</td></tr>";
    document.getElementById("prog").textContent = t("progress", { a: seen.filter(function (p) { return D.files.some(function (f) { return f.path === p; }); }).length, b: D.files.length });
  }
  document.getElementById("files").addEventListener("change", function (e) {
    var p = e.target.getAttribute("data-p");
    if (!p) return;
    var i = seen.indexOf(p);
    if (e.target.checked && i < 0) seen.push(p);
    if (!e.target.checked && i >= 0) seen.splice(i, 1);
    store.set("seen", seen);
    renderFiles();
  });
  document.querySelectorAll("#file-filter button").forEach(function (b) {
    b.addEventListener("click", function () {
      filter = b.getAttribute("data-f");
      document.querySelectorAll("#file-filter button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      renderFiles();
    });
  });
  renderFiles();

  /* ---------------------------------------------------------------- map + its default panel */
  var pinChecks = {}, moduleNotes = R.module_notes || {};
  (R.pin_checks || []).forEach(function (c) { (pinChecks[c.module] = pinChecks[c.module] || []).push(c); });

  function overview(ctx) {
    var mods = D.map.modules, status = OV.status;
    var internal = Object.keys(mods).filter(function (id) { return mods[id].kind !== "external"; });
    var direct = internal.filter(function (id) { return ["chg", "new", "del"].indexOf(status[id]) >= 0; });
    var aff = internal.filter(function (id) { return status[id] === "aff"; });
    var flowsTouched = D.map.flows.filter(function (f) { return ctx.flowStatus(f); });
    var changes = [];
    var newMods = internal.filter(function (id) { return status[id] === "new"; });
    var delMods = internal.filter(function (id) { return status[id] === "del"; });
    if (newMods.length) changes.push({ p: t("ch_new_modules"), c: "ok", t: t("ch_new_modules_t", { n: newMods.length, list: newMods.slice(0, 4).join(", ") }), go: newMods[0] });
    if (delMods.length) changes.push({ p: t("ch_deleted"), c: "crit", t: t("ch_deleted_t", { n: delMods.length, list: delMods.slice(0, 4).join(", ") }), go: delMods[0] });
    if (D.external.added.length) changes.push({ p: t("ch_new_dep"), c: "warn", t: t("ch_new_dep_t", { list: D.external.added.join(", ") }), go: "ext:" + D.external.added[0] });
    var gname = {};
    D.map.groups.forEach(function (g) { gname[g.id] = g.name; });
    D.group_links.forEach(function (l) { changes.push({ p: t("ch_new_link"), c: "info", t: t("ch_new_link_t", { a: gname[l[0]] || l[0], b: gname[l[1]] || l[1] }), grp: l[0] }); });
    D.config.forEach(function (c) {
      changes.push({ p: t("ch_config"), c: c.readers.length > 1 ? "warn" : "info", t: t("ch_config_t", { key: c.key, old: c.old == null ? "—" : c.old, new: c["new"] == null ? "—" : c["new"], n: c.readers.length }), go: c.file });
    });
    var pinMods = {};
    D.pins.forEach(function (p) { pinMods[p.module] = true; });
    if (D.pins.length) changes.push({ p: t("ch_pins"), c: "info", t: t("ch_pins_t", { n: D.pins.length, m: Object.keys(pinMods).length }), go: Object.keys(pinMods)[0] });
    (R.structure || []).forEach(function (s) { changes.push({ p: s.tag || t("sev_" + s.severity), c: SEV_PILL[s.severity], t: s.title, go: s.module }); });
    return '<div class="ph"><span class="label">' + esc(t("overlay_branch")) + '</span><h3 class="mono-title">' + esc(D.branch || short(D.head.sha)) + '</h3><p class="small">' +
      esc(t("relative_to", { base: D.base.ref, sha: short(D.merge_base), n: D.commits.length })) + "</p></div>" +
      '<div class="nums"><div><b>' + direct.length + "/" + internal.length + "</b><span>" + esc(t("n_direct")) + "</span></div><div><b>" + aff.length + "</b><span>" + esc(t("n_affected")) + "</span></div>" +
      (D.map.flows.length ? "<div><b>" + flowsTouched.length + "/" + D.map.flows.length + "</b><span>" + esc(t("n_flows")) + "</span></div>" : "") + "</div>" +
      (changes.length ? '<div class="blk"><span class="label">' + esc(t("map_changes")) + '</span><ul class="changes">' + changes.map(function (c) {
        var inner = '<span class="pill ' + esc(c.c || "info") + '">' + esc(c.p) + "</span><span>" + esc(c.t) + "</span>";
        if (c.go && D.map.modules[c.go]) return '<li><button type="button" data-go="' + esc(c.go) + '">' + inner + "</button></li>";
        if (c.grp) return '<li><button type="button" data-grp="' + esc(c.grp) + '">' + inner + "</button></li>";
        return '<li class="static">' + inner + "</li>";
      }).join("") + "</ul></div>" : "") +
      (D.map.flows.length ? '<div class="blk"><span class="label">' + esc(t("flows_touched")) + '</span><ul class="fl-list">' + D.map.flows.map(function (f) {
        var s = ctx.flowStatus(f);
        return '<li><button type="button" data-flow="' + esc(f.id) + '"><i style="background:var(--f' + f.color + ')"></i><span>' + esc(f.name) + "</span>" +
          (s ? '<span class="pill ' + (s === "direct" ? "info" : "warn") + '">' + esc(t("flow_" + s)) + "</span>" : "") + "</button></li>";
      }).join("") + "</ul></div>" : "") +
      '<p class="hint">' + esc(t("report_map_hint")) + "</p>";
  }
  var ctrl = AtlasMap.create(document.getElementById("atlas-map"), D.map, {
    t: t, lang: lang, defaultPanel: overview, extras: { pinChecks: pinChecks, moduleNotes: moduleNotes },
  });
  var structure = document.getElementById("structure");
  if (structure) structure.addEventListener("click", function (e) {
    var b = e.target.closest("[data-go]");
    if (b) { ctrl.go(b.getAttribute("data-go")); document.getElementById("atlas-map").scrollIntoView({ block: "start" }); }
  });
})();
