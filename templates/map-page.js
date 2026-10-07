/* Standalone project map page. Data: render.build_map_page(). */
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("atlas-data").textContent);
  var t = AtlasI18n.t(D.lang), esc = AtlasMap.esc, fmt = AtlasMap.fmt;
  var M = D.maintenance;

  function when(iso) { return (iso || "").slice(0, 16).replace("T", " "); }

  function overview(ctx) {
    var groups = D.map.groups.filter(function (g) { return g.id.charAt(0) !== "_"; }).length;
    var stale = M.stale.map(function (id) { return AtlasMap.mchip(ctx, id); }).join("");
    return '<div class="ph"><span class="label">' + esc(t("map_overview")) + "</span><h3>" + esc(D.repo) + '</h3><p class="small">' +
      esc(t("based_on_rev", { rev: D.rev.slice(0, 7), date: when(D.rev_date) })) + "</p></div>" +
      '<div class="nums"><div><b>' + fmt(M.modules, D.lang) + "</b><span>" + esc(t("modules")) + "</span></div>" +
      "<div><b>" + groups + "</b><span>" + esc(t("groups")) + "</span></div>" +
      "<div><b>" + D.map.flows.length + "</b><span>" + esc(t("flows")) + "</span></div>" +
      "<div><b>" + fmt(D.map.edges.filter(function (e) { return e.k === "dep"; }).length, D.lang) + "</b><span>" + esc(t("dependencies")) + "</span></div></div>" +
      '<div class="blk"><span class="label">' + esc(t("maintenance")) + "</span>" +
      '<div class="mrow">' + AtlasMap.PROV(t, "fact") + "<span>" + esc(t("maint_facts", { rev: D.rev.slice(0, 7) })) + "</span></div>" +
      '<div class="mrow">' + AtlasMap.PROV(t, "ai") + "<span>" + esc(t("maint_pages", { ok: M.pages_current, n: M.modules })) + "</span>" +
      (stale ? '<span class="chips">' + stale + "</span>" : "") + "</div>" +
      '<div class="mrow">' + AtlasMap.PROV(t, "pin") + "<span>" + esc(t("maint_pins", { n: M.pins })) + "</span></div></div>" +
      (M.recent.length ? '<div class="blk"><span class="label">' + esc(t("recent_updates")) + '</span><ul class="log">' + M.recent.map(function (r) {
        return '<li><span class="when">' + esc(when(r.date).slice(5)) + "</span><span>" + esc(r.subject) + ' <span class="small mono">' + esc(r.sha) + "</span></span></li>";
      }).join("") + "</ul></div>" : "") +
      (D.map.configured ? "" : '<p class="hint warnt">' + esc(t("map_unconfigured")) + "</p>") +
      '<p class="hint">' + esc(t("map_hint")) + "</p>";
  }

  var app = document.getElementById("app");
  app.innerHTML =
    '<header><div class="meta"><span class="mono">' + esc(D.repo) + "</span><span>·</span><span>" +
      esc(t("based_on_rev", { rev: D.rev.slice(0, 7), date: when(D.rev_date) })) + "</span><span>·</span><span>" +
      esc(t("granularity_" + D.granularity)) + "</span></div>" +
      "<h1>" + esc(t("map_heading", { repo: D.repo })) + '</h1><p class="lede">' + esc(t("map_lede")) + "</p></header>" +
    '<section id="atlas-map" aria-label="' + esc(t("map_aria")) + '"></section>' +
    '<section aria-labelledby="h-how"><h2 id="h-how">' + esc(t("how_title")) + '</h2><div class="how-grid">' +
      '<div class="panel hw">' + AtlasMap.PROV(t, "fact") + "<h3>" + esc(t("how_facts")) + "</h3><p>" + esc(t("how_facts_body")) + "</p></div>" +
      '<div class="panel hw">' + AtlasMap.PROV(t, "ai") + "<h3>" + esc(t("how_pages")) + "</h3><p>" + esc(t("how_pages_body")) + "</p></div>" +
      '<div class="panel hw">' + AtlasMap.PROV(t, "pin") + "<h3>" + esc(t("how_pins")) + "</h3><p>" + esc(t("how_pins_body")) + "</p></div>" +
      '<div class="panel hw"><span class="label">' + esc(t("how_where")) + "</span><pre>.project-map/\n├─ atlas.json   " + esc(t("tree_atlas")) +
      "\n├─ map.json     " + esc(t("tree_facts")) + "\n├─ pins.md      " + esc(t("tree_pins")) + "\n└─ modules/*.md " + esc(t("tree_pages")) + "</pre></div>" +
    "</div></section>" +
    "<footer><span>" + esc(D.tool) + "</span><span>" + esc(t("generated_at", { when: when(D.generated_at) })) + "</span></footer>";

  AtlasMap.create(document.getElementById("atlas-map"), D.map, { t: t, lang: D.lang, defaultPanel: overview });
})();
