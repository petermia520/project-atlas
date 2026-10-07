"""The `.project-map/` directory: structure (atlas.json), explanations, pins, and their checks.

    .project-map/
      atlas.json          layers, groups, flows, scan settings   (AI proposes, people review)
      map.json            facts for the main branch               (generated, never hand-edited)
      pins.md             notes people pin to modules             (people only)
      modules/<slug>.md   one explanation page per module         (AI writes)
      modules/<slug>.pending.md   rewrite waiting for the owner   (AI writes, owner approves)
"""

import json
import os
import posixpath
import re

from . import gitio, globs

DIR = ".project-map"
PIN_LINE = re.compile(r"^\s*[-*]\s+(?P<text>.+?)(?:\s+(?:—|--|–)\s+(?P<by>@?[^,]+?)(?:,\s*(?P<date>\d{4}-\d{2}-\d{2}))?)?\s*$")


class AtlasError(ValueError):
    pass


def atlas_dir(root):
    return os.path.join(root, DIR)


def load_atlas(root):
    path = os.path.join(atlas_dir(root), "atlas.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise AtlasError("%s is not valid JSON: %s" % (path, exc))


def load_facts(root):
    path = os.path.join(atlas_dir(root), "map.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def slug(module_id):
    s = re.sub(r"[^A-Za-z0-9._-]+", "__", module_id).strip("_")
    return s or "root"


def page_path(root, module_id, pending=False):
    return os.path.join(atlas_dir(root), "modules", slug(module_id) + (".pending.md" if pending else ".md"))


def parse_page(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 4:]
    return meta, body.strip()


def load_pages(root):
    """{module_id: {"meta", "about", "pending": {...} | None, "file"}}"""
    pages = {}
    folder = os.path.join(atlas_dir(root), "modules")
    if not os.path.isdir(folder):
        return pages
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as fh:
            meta, body = parse_page(fh.read())
        mid = meta.get("module")
        if not mid:
            continue
        entry = pages.setdefault(mid, {"meta": {}, "about": "", "pending": None, "file": None})
        if name.endswith(".pending.md"):
            entry["pending"] = {"meta": meta, "about": body, "file": name}
        else:
            entry.update(meta=meta, about=body, file=name)
    return pages


def load_pins(root):
    """[{pattern, text, by, date}] from pins.md (## <module id or glob> headings, bullet notes)."""
    path = os.path.join(atlas_dir(root), "pins.md")
    if not os.path.isfile(path):
        return []
    pins, pattern = [], None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("## "):
                pattern = line[3:].strip().strip("`").strip()
                continue
            if pattern is None:
                continue
            m = PIN_LINE.match(line)
            if m:
                pins.append({"pattern": pattern, "text": m.group("text").strip(),
                             "by": (m.group("by") or "").strip() or None, "date": m.group("date")})
    return pins


def pins_for(module_id, pins):
    return [p for p in pins if p["pattern"] == module_id or globs.match(module_id, p["pattern"])]


def layers_of(atlas, used):
    layers = list((atlas or {}).get("layers") or [])
    ids = {l["id"] for l in layers}
    for lid, name in used:
        if lid not in ids:
            layers.append({"id": lid, "name": name})
            ids.add(lid)
    return layers


def _auto_group_key(mid, granularity="file"):
    """Files group by their directory; directory modules group by their parent directory."""
    parent = posixpath.dirname(mid)
    if granularity == "dir":
        return parent or "."
    return parent or "."


def group_modules(module_ids, atlas, kinds=None, names=None, granularity="file"):
    """(groups, {module_id: group_id}); unmatched modules land in an "unassigned" group.

    names: {"unassigned": "...", "config": "...", "modules": "..."} for the fallback groups.
    """
    names = names or {}
    kinds = kinds or {}
    groups, assign = [], {}
    defined = list((atlas or {}).get("groups") or [])
    for g in defined:
        groups.append({"id": g["id"], "name": g.get("name", g["id"]), "layer": g.get("layer", "modules"),
                       "about": g.get("about", ""), "include": g.get("include", []), "modules": []})
    by_id = {g["id"]: g for g in groups}
    leftovers = []
    for mid in sorted(module_ids):
        hit = None
        for g, spec in zip(groups, defined):
            if globs.match_any(mid, spec.get("include")) and not globs.match_any(mid, spec.get("exclude")):
                hit = g
                break
        if hit:
            hit["modules"].append(mid)
            assign[mid] = hit["id"]
        else:
            leftovers.append(mid)
    if leftovers:
        if defined:
            g = {"id": "_unassigned", "name": names.get("unassigned", "Unassigned"), "layer": "_other",
                 "about": "", "include": [], "modules": leftovers, "auto": True}
            groups.append(g)
            for mid in leftovers:
                assign[mid] = g["id"]
        else:
            for mid in leftovers:
                is_cfg = kinds.get(mid) == "config"
                key = "_config" if is_cfg else _auto_group_key(mid, granularity)
                if key not in by_id:
                    g = {"id": key, "name": names.get("config", "config") if is_cfg else (key + "/" if key != "." else "(root)"),
                         "layer": "_other" if is_cfg else "_modules", "about": "", "include": [], "modules": [], "auto": True}
                    groups.append(g)
                    by_id[key] = g
                by_id[key]["modules"].append(mid)
                assign[mid] = key
    groups = [g for g in groups if g["modules"] or not g.get("auto")]
    return groups, assign


def check(root, facts, atlas=None, pages=None, pins=None):
    """{"errors": [...], "warnings": [...]} for .project-map against `facts`."""
    errors, warnings = [], []
    atlas = load_atlas(root) if atlas is None else atlas
    pages = load_pages(root) if pages is None else pages
    pins = load_pins(root) if pins is None else pins
    mods = facts["modules"]
    if atlas is None:
        errors.append("missing %s/atlas.json" % DIR)
        return {"errors": errors, "warnings": warnings}
    if atlas.get("schema") != 1:
        warnings.append("atlas.json: schema should be 1")
    layer_ids = [l.get("id") for l in atlas.get("layers", [])]
    if len(layer_ids) != len(set(layer_ids)):
        errors.append("atlas.json: duplicate layer ids")
    seen = set()
    for g in atlas.get("groups", []):
        if not g.get("id") or not g.get("include"):
            errors.append("atlas.json: every group needs an id and include globs (%r)" % g.get("id"))
        if g.get("id") in seen:
            errors.append("atlas.json: duplicate group id %s" % g.get("id"))
        seen.add(g.get("id"))
        if layer_ids and g.get("layer") not in layer_ids:
            errors.append("atlas.json: group %s uses unknown layer %r" % (g.get("id"), g.get("layer")))
    groups, assign = group_modules(mods, atlas)
    for g in groups:
        if not g["modules"] and not g.get("auto"):
            warnings.append("group %s matches no modules" % g["id"])
    unassigned = [m for m, gid in assign.items() if gid == "_unassigned"]
    if unassigned:
        warnings.append("%d modules match no group: %s" % (len(unassigned), ", ".join(unassigned[:12]) + (" ..." if len(unassigned) > 12 else "")))
    flow_ids = set()
    for f in atlas.get("flows", []):
        if not f.get("id") or f["id"] in flow_ids:
            errors.append("atlas.json: flows need unique ids (%r)" % f.get("id"))
        flow_ids.add(f.get("id"))
        for chain in f.get("chains", []):
            if len(chain) < 2:
                errors.append("flow %s: a chain needs at least two modules" % f.get("id"))
            for mid in chain:
                if mid not in mods:
                    errors.append("flow %s: unknown module %s" % (f.get("id"), mid))
    for ext in atlas.get("external", []):
        if ext not in facts.get("external", {}):
            warnings.append("external package %s is not imported anywhere" % ext)
    orphans = [m for m in pages if m not in mods]
    if orphans:
        warnings.append("%d module pages have no module: %s" % (len(orphans), ", ".join(orphans[:12])))
    missing = [m for m in mods if m not in pages]
    if missing:
        warnings.append("%d modules have no explanation page yet" % len(missing))
    for p in pins:
        if not any(p["pattern"] == m or globs.match(m, p["pattern"]) for m in mods):
            warnings.append("pin heading %r matches no module" % p["pattern"])
    return {"errors": errors, "warnings": warnings}


def _changed_lines(repo, since_rev, rev, paths):
    if not since_rev or not gitio.try_resolve(repo, since_rev):
        return None
    out = gitio.git(repo, "diff", "--numstat", since_rev, rev, "--", *paths, check=False)
    total = 0
    for line in out.splitlines():
        a, d, _ = (line.split("\t", 2) + ["", ""])[:3]
        total += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    return total


def stale(root, repo, facts, threshold=0.3, pages=None):
    """Which explanation pages to write or rewrite.

    state: missing  -> write a page
           changed  -> rewrite in place (change ratio <= threshold)
           major    -> write a .pending.md page for the owner to approve
           pending  -> a pending page is waiting for approval
           orphan   -> the module is gone; delete the page
    """
    pages = load_pages(root) if pages is None else pages
    out = []
    for mid, m in sorted(facts["modules"].items()):
        page = pages.get(mid)
        if not page or not page.get("file"):
            out.append({"module": mid, "state": "pending" if page and page.get("pending") else "missing", "ratio": None})
            continue
        if page["meta"].get("hash") == m["hash"]:
            if page.get("pending"):
                out.append({"module": mid, "state": "pending", "ratio": None})
            continue
        changed = _changed_lines(repo, page["meta"].get("rev"), facts["rev"], m["files"])
        ratio = 1.0 if changed is None else round(changed / float(max(m["loc"], 1)), 2)
        if page.get("pending") and page["pending"]["meta"].get("hash") == m["hash"]:
            out.append({"module": mid, "state": "pending", "ratio": ratio})
        else:
            out.append({"module": mid, "state": "major" if ratio > threshold else "changed", "ratio": ratio,
                        "page_rev": page["meta"].get("rev")})
    for mid in pages:
        if mid not in facts["modules"]:
            out.append({"module": mid, "state": "orphan", "ratio": None})
    return out


def approve(root, module_id):
    pending = page_path(root, module_id, pending=True)
    if not os.path.isfile(pending):
        raise AtlasError("no pending page for %s" % module_id)
    os.replace(pending, page_path(root, module_id))
    return page_path(root, module_id)


def recent_updates(repo, limit=8):
    out = gitio.git(repo, "log", "-n", str(limit), "--format=%h%x1f%cI%x1f%s", "--", DIR, check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
    return rows


def freshness(mid, module, page):
    """(state, details) for the map panel: current | stale | pending | missing."""
    if not page or not page.get("file"):
        return ("pending" if page and page.get("pending") else "missing"), {}
    meta = page["meta"]
    if page.get("pending"):
        return "pending", {"rev": meta.get("rev")}
    if meta.get("hash") == module.get("hash"):
        return "current", {"rev": meta.get("rev")}
    return "stale", {"rev": meta.get("rev")}


def module_rel(path, root):
    return posixpath.normpath(os.path.relpath(path, root).replace(os.sep, "/"))
