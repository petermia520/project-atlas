"""Turn facts / impact / report JSON into self-contained HTML pages.

The page templates live in ../../templates. Python prepares a view model; the bundled
JavaScript lays out and draws it. Output is a single file with inline CSS, JS and data.
"""

import collections
import datetime
import html
import json
import os
import posixpath

from . import __version__, gitio, project

TEMPLATES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "templates"))
STRINGS = {
    "zh": {"unassigned": "未归类", "config": "配置", "external": "第三方库", "modules": "模块", "other": "其他",
           "map_title": "项目地图", "report_title": "分支审阅报告"},
    "en": {"unassigned": "Unassigned", "config": "Config", "external": "Third-party", "modules": "Modules",
           "other": "Other", "map_title": "project map", "report_title": "branch review"},
}
STATUS = {"changed": "chg", "new": "new", "deleted": "del", "affected": "aff"}


def ui_lang(*sources):
    for src in sources:
        code = (src or {}).get("language")
        if code:
            return "zh" if str(code).lower().startswith("zh") else "en"
    return "en"


def repo_name(root, atlas=None):
    if atlas and atlas.get("name"):
        return atlas["name"]
    url = gitio.remote_url(root) if root else None
    if url:
        return url.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")
    return os.path.basename(os.path.abspath(root or "."))


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _dedupe_labels(groups, modules):
    for g in groups:
        seen = collections.Counter(modules[m]["label"] for m in g["modules"])
        for m in g["modules"]:
            if seen[modules[m]["label"]] > 1:
                parts = m.rstrip("/").split("/")
                stem = parts[-1].rsplit(".", 1)[0] if modules[m]["kind"] == "source" and "." in parts[-1] else parts[-1]
                modules[m]["label"] = "/".join(parts[-2:-1] + [stem])


def build_map_model(root, facts, atlas, pages, pins, lang, overlay=None, extra_edges=None):
    """View model shared by the standalone map and the report's impact section."""
    s = STRINGS[lang]
    atlas = atlas or {}
    raw = dict(facts["modules"])
    if overlay:
        for mid, info in (overlay.get("base_only_modules") or {}).items():
            raw[mid] = dict(info, files=[], symbols=[], imports={}, ext=[], config_reads=[], owners=[],
                            churn30=0, coverage=None, hash=None)
    kinds = {m: info["kind"] for m, info in raw.items()}
    groups, assign = project.group_modules(raw.keys(), atlas, kinds,
                                           names={"unassigned": s["unassigned"], "config": s["config"]},
                                           granularity=facts.get("granularity", "file"))

    show_ext = set(atlas.get("external") or [])
    if overlay:
        show_ext |= set(overlay.get("external_added") or [])
    ext_layer = atlas.get("external_layer") or "_other"
    if show_ext:
        ext_group = {"id": "_external", "name": s["external"], "layer": ext_layer, "about": "", "modules": [], "auto": True}
        for name in sorted(show_ext):
            mid = "ext:" + name
            raw[mid] = {"kind": "external", "lang": None, "label": name, "loc": 0, "files": [], "symbols": [],
                        "imports": {}, "ext": [], "config_reads": [], "owners": [], "churn30": 0, "coverage": None,
                        "hash": None, "version": (facts.get("external", {}).get(name) or {}).get("version")}
            ext_group["modules"].append(mid)
            assign[mid] = "_external"
        groups.append(ext_group)

    edges = {}
    for a, b in facts["edges"]:
        edges[(a, b)] = "dep"
    for mid, info in facts["modules"].items():
        for e in info.get("ext", []):
            if e in show_ext:
                edges[(mid, "ext:" + e)] = "dep"
    if overlay:
        for a, b in overlay.get("edges_added") or []:
            edges[(a, b)] = "new"
        for a, b in overlay.get("ext_edges") or []:
            edges[(a, "ext:" + b)] = "new"
    for e in extra_edges or []:
        a, b = e.get("from"), e.get("to")
        if a in raw and b in raw:
            edges[(a, b)] = e.get("kind", "miss")

    callers, deps = collections.defaultdict(list), collections.defaultdict(list)
    for (a, b), k in edges.items():
        if k == "miss":
            continue
        deps[a].append(b)
        callers[b].append(a)

    modules = {}
    for mid, info in raw.items():
        page = pages.get(mid)
        fresh, fmeta = project.freshness(mid, info, page) if info["kind"] != "external" else ("current", {})
        pending = (page or {}).get("pending")
        modules[mid] = {
            "label": info.get("label") or mid, "path": mid if info["kind"] != "external" else info["label"],
            "kind": info["kind"], "lang": info.get("lang"), "loc": info.get("loc", 0), "group": assign.get(mid),
            "files": info.get("files", [])[:50], "owners": info.get("owners", []), "churn": info.get("churn30", 0),
            "coverage": info.get("coverage"), "version": info.get("version"),
            "about": (page or {}).get("about", ""), "refs": ((page or {}).get("meta") or {}).get("refs"),
            "fresh": fresh, "fresh_rev": fmeta.get("rev"),
            "pending_about": pending["about"] if pending else None,
            "pins": [{"text": p["text"], "by": p["by"], "date": p["date"]} for p in project.pins_for(mid, pins)],
            "symbols": [{k: sym.get(k) for k in ("name", "kind", "line", "complexity", "sig", "file")}
                        for sym in info.get("symbols", [])][:60],
            "config_reads": info.get("config_reads", []), "ext": info.get("ext", []),
            "callers": sorted(set(callers.get(mid, []))), "deps": sorted(set(deps.get(mid, []))),
        }
    _dedupe_labels(groups, modules)

    used_layers = []
    for g in groups:
        if g["layer"] == "_other":
            used_layers.append(("_other", s["other"]))
        elif g["layer"] == "_modules":
            used_layers.append(("_modules", s["modules"]))
        elif g["layer"] not in {l["id"] for l in atlas.get("layers", [])}:
            used_layers.append((g["layer"], g["layer"]))
    layers = project.layers_of(atlas, used_layers)
    order = {l["id"]: i for i, l in enumerate(layers)}
    groups.sort(key=lambda g: order.get(g["layer"], 99))

    flows = []
    for i, f in enumerate(atlas.get("flows") or []):
        chains = [[m for m in chain if m in modules] for chain in f.get("chains", [])]
        chains = [c for c in chains if len(c) >= 2]
        if chains:
            flows.append({"id": f["id"], "name": f.get("name", f["id"]), "about": f.get("about", ""),
                          "chains": chains, "color": i % 8})

    return {
        "layers": [{"id": l["id"], "name": l.get("name", l["id"])} for l in layers],
        "groups": [{"id": g["id"], "name": g["name"], "layer": g["layer"], "about": g.get("about", ""),
                    "include": g.get("include", []), "modules": g["modules"]} for g in groups],
        "modules": modules,
        "edges": [{"a": a, "b": b, "k": k} for (a, b), k in sorted(edges.items())],
        "flows": flows,
        "configured": bool(atlas.get("groups")),
    }


def build_overlay(impact):
    status, details = {}, {}
    for mid, m in impact["modules"].items():
        status[mid] = STATUS[m["status"]]
        details[mid] = {"added": m.get("added", 0), "deleted": m.get("deleted", 0), "files": m.get("files", []),
                        "symbols": m.get("symbols", [])[:40], "reasons": m.get("reasons", [])}
    for name in impact["external"]["added"]:
        status["ext:" + name] = "new"
    return {
        "branch": impact.get("branch"), "status": status, "details": details,
        "edges_added": impact["edges"]["added"], "ext_edges": impact["external"]["edges"],
        "external_added": impact["external"]["added"], "base_only_modules": impact.get("base_only_modules", {}),
    }


def build_map_page(root, facts, atlas, pages, pins):
    lang = ui_lang(atlas)
    model = build_map_model(root, facts, atlas, pages, pins, lang)
    stale = [m for m, info in model["modules"].items() if info["fresh"] in ("stale", "pending")]
    return {
        "kind": "map", "lang": lang, "tool": "project-atlas " + __version__, "generated_at": _now(),
        "repo": repo_name(root, atlas), "rev": facts["rev"], "rev_date": facts.get("rev_date"),
        "granularity": facts.get("granularity"), "map": model,
        "maintenance": {
            "modules": sum(1 for m in model["modules"].values() if m["kind"] != "external"),
            "pages_current": sum(1 for m in model["modules"].values() if m["fresh"] == "current" and m["kind"] != "external"),
            "stale": stale, "pins": len(pins), "recent": project.recent_updates(root) if root else [],
        },
    }


def build_report_page(root, impact, sessions, report, checks, atlas, pages, pins, baseline=None):
    report = report or {}
    lang = ui_lang(report, atlas)
    overlay = build_overlay(impact)
    model = build_map_model(root, impact["head_facts"], atlas, pages, pins, lang, overlay=overlay,
                            extra_edges=[e for f in report.get("structure", []) for e in f.get("edges", [])])
    model["overlay"] = overlay
    by_kind = impact["lines"]["by_kind"]
    src = by_kind.get("source", {"added": 0, "deleted": 0, "files": 0})
    tst = by_kind.get("test", {"added": 0, "deleted": 0, "files": 0})
    sess = sessions or {"sessions": [], "totals": {}, "trailers": []}
    task = report.get("task") or next((s.get("task") for s in sess.get("sessions", []) if s.get("task")), None)
    review_order = report.get("review_order") or []
    notes = report.get("file_notes") or {}
    files = []
    for f in impact["files"]:
        if f["kind"] in ("atlas",):
            continue
        files.append(dict(f, order=(review_order.index(f["path"]) + 1) if f["path"] in review_order else None,
                          note=notes.get(f["path"]), status_mod=overlay["status"].get(f.get("module"))))
    files.sort(key=lambda f: (f["order"] is None, f["order"] or 0, {"source": 0, "config": 1, "manifest": 2, "test": 3}.get(f["kind"], 4), f["path"]))
    ci = checks or {}
    return {
        "kind": "report", "lang": lang, "tool": "project-atlas " + __version__, "generated_at": _now(),
        "repo": repo_name(root, atlas), "branch": impact.get("branch"), "base": impact["base"], "head": impact["head"],
        "merge_base": impact["merge_base"], "task": task, "report": report,
        "stats": {
            "source": src, "test": tst, "files": len(files), "commits": len(impact["commits"]),
            "tests_added": impact["tests"]["added"], "tests_removed": impact["tests"]["removed"],
            "skipped": impact["tests"]["skipped_added"],
            "sessions": len(sess.get("sessions", [])), "human_messages": (sess.get("totals") or {}).get("human_messages", 0),
            "tokens": sess.get("totals") or {},
        },
        "lines": impact["lines"], "baseline": baseline, "files": files, "commits": impact["commits"],
        "config": impact["config"], "flows_touched": impact["flows"], "pins": impact["pins"],
        "group_links": impact["groups"]["new_links"], "external": impact["external"],
        "edges": impact["edges"], "sessions": sess, "checks": report.get("checks") or ci.get("checks") or [],
        "checks_source": None if report.get("checks") else ci.get("source") or ci.get("reason"),
        "map": model, "warnings": impact.get("warnings", []),
    }


def _read(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
        return fh.read()


def write_html(model, out, title, fragment=False):
    scripts = ["i18n.js", "map-view.js", "map-page.js" if model["kind"] == "map" else "report-page.js"]
    js = "\n;\n".join(_read(n) for n in scripts)
    css = _read("atlas.css")
    data = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = _read("page.html")
    page = page.replace("__LANG__", "zh-CN" if model["lang"] == "zh" else "en")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("/*__CSS__*/", css).replace("__DATA__", data).replace("/*__JS__*/", js)
    if fragment:
        head_start = page.index("<title>")
        head_end = page.index("</head>")
        body_start = page.index("<body>") + len("<body>")
        body_end = page.rindex("</body>")
        page = page[head_start:head_end].replace('<meta charset="utf-8">', "") + page[body_start:body_end]
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out


def default_title(model):
    s = STRINGS[model["lang"]]
    if model["kind"] == "map":
        return "%s %s" % (model["repo"], s["map_title"])
    branch = model.get("branch") or gitio.short(model["head"]["sha"])
    return "%s %s" % (posixpath.basename(branch), s["report_title"])
