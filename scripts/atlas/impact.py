"""What a branch changes, computed from git: files, lines, symbols, modules, dependencies.

Everything here is deterministic. Judgement (scope, risk, decisions) is left to the agent,
which reads this output and writes report.json.
"""

import collections
import difflib
import re

from . import SCHEMA, __version__, facts as factsmod, gitio, globs, langs, project
from .classify import Classifier

TEST_FN = re.compile(r"(^|\.)test_?\w*$|(^|\.)Test\w*\.test\w*$")
JS_TEST_CALL = re.compile(r"""\b(?:it|test)(?:\.(?:only|concurrent|each\([^)]*\)))?\s*\(\s*['"`]""")
SKIP_MARK = re.compile(r"@pytest\.mark\.(?:skip|xfail)\b|@unittest\.skip|\b(?:it|test|describe)\.(?:skip|todo)\s*\(|\bx(?:it|describe|test)\s*\(|\bt\.Skip\(")
TRAILER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.+)$")


def parse_commits(repo, rev_range):
    out = gitio.git(repo, "log", "--reverse", "--format=%H%x1f%an%x1f%aI%x1f%s%x1f%(trailers:unfold,only)%x1e", rev_range)
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, author, date, subject, trailers = (rec.split("\x1f") + [""] * 5)[:5]
        tr = []
        for line in trailers.splitlines():
            m = TRAILER.match(line.strip())
            if m:
                tr.append({"key": m.group(1), "value": m.group(2).strip()})
        commits.append({"sha": sha, "author": author, "date": date, "subject": subject, "trailers": tr})
    return commits


def diff_files(repo, a, b, classify):
    """[{path, old_path, status, added, deleted, binary, kind, lang}]"""
    status = {}
    toks = gitio.git(repo, "diff", "--name-status", "-z", "-M", a, b).split("\0")
    i = 0
    while i < len(toks) - 1:
        st = toks[i]
        if not st:
            i += 1
            continue
        if st[0] in "RC":
            status[toks[i + 2]] = (st[0], toks[i + 1])
            i += 3
        else:
            status[toks[i + 1]] = (st[0], None)
            i += 2
    files = []
    toks = gitio.git(repo, "diff", "--numstat", "-z", "-M", a, b).split("\0")
    i = 0
    while i < len(toks):
        tok = toks[i]
        if not tok:
            i += 1
            continue
        parts = tok.split("\t")
        if len(parts) == 3 and parts[2] == "":
            old, path = toks[i + 1], toks[i + 2]
            i += 3
        else:
            old, path = None, parts[2]
            i += 1
        st, old2 = status.get(path, ("M", None))
        kind, lang = classify(path)
        files.append({"path": path, "old_path": old or old2, "status": st,
                      "added": int(parts[0]) if parts[0].isdigit() else 0,
                      "deleted": int(parts[1]) if parts[1].isdigit() else 0,
                      "binary": parts[0] == "-", "kind": kind or "excluded", "lang": lang})
    return files


def added_lines(repo, a, b, paths):
    """{path: [(new_lineno, text)]} and {path: [old_text]} from a zero-context diff."""
    added, removed = collections.defaultdict(list), collections.defaultdict(list)
    if not paths:
        return added, removed
    out = gitio.git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", "-M", a, b, "--", *paths)
    current, line_no = None, 0
    for line in out.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            line_no = int(m.group(1)) if m else 0
        elif current and line.startswith("+"):
            added[current].append((line_no, line[1:]))
            line_no += 1
        elif current and line.startswith("-"):
            removed[current].append(line[1:])
    return added, removed


def _symbol_key(s):
    return (s.get("file", ""), s["name"])


def _body(texts, s):
    text = texts.get(s.get("file")) if s.get("file") else None
    if text is None:
        return ""
    return "\n".join(text.splitlines()[s["line"] - 1:s["end"]])


def symbol_changes(base_mod, head_mod, base_texts, head_texts, base_files, head_files):
    """[{name, change, ...}] for symbols added, removed, renamed, modified or re-signed."""
    def with_file(mod, files):
        out = []
        for s in mod["symbols"]:
            s = dict(s)
            s.setdefault("file", files[0] if len(files) == 1 else s.get("file"))
            out.append(s)
        return out

    b = {_symbol_key(s): s for s in with_file(base_mod, base_files)}
    h = {_symbol_key(s): s for s in with_file(head_mod, head_files)}
    changes = []
    for key in sorted(set(b) & set(h)):
        sb, sh = b[key], h[key]
        if sb["hash"] == sh["hash"]:
            continue
        kind = "signature" if sb.get("sig") != sh.get("sig") else "modified"
        changes.append({"name": key[1], "file": key[0] or None, "kind": sh["kind"], "change": kind,
                        "sig": [sb.get("sig"), sh.get("sig")] if kind == "signature" else None,
                        "complexity": [sb.get("complexity"), sh.get("complexity")], "line": sh["line"]})
    removed = [b[k] for k in sorted(set(b) - set(h))]
    added = [h[k] for k in sorted(set(h) - set(b))]
    paired = set()
    for r in removed:
        best, best_ratio = None, 0.0
        rb = _body(base_texts, r)
        for a in added:
            if id(a) in paired or a["kind"] != r["kind"]:
                continue
            ratio = difflib.SequenceMatcher(None, rb, _body(head_texts, a)).quick_ratio() if rb else 0.0
            if ratio > best_ratio:
                best, best_ratio = a, ratio
        if best is not None and best_ratio >= 0.5:
            paired.add(id(best))
            changes.append({"name": best["name"], "file": best.get("file"), "kind": best["kind"], "change": "renamed",
                            "from": r["name"], "similarity": round(best_ratio, 2),
                            "sig": [r.get("sig"), best.get("sig")], "complexity": [r.get("complexity"), best.get("complexity")],
                            "line": best["line"]})
        else:
            changes.append({"name": r["name"], "file": r.get("file"), "kind": r["kind"], "change": "removed",
                            "complexity": [r.get("complexity"), None], "line": None})
    for a in added:
        if id(a) not in paired:
            changes.append({"name": a["name"], "file": a.get("file"), "kind": a["kind"], "change": "added",
                            "complexity": [None, a.get("complexity")], "line": a["line"]})
    # A class "changes" whenever one of its methods does; keep the method-level entries only.
    owners = {c["name"].split(".")[0] for c in changes if "." in c["name"]}
    changes = [c for c in changes if not (c["kind"] == "class" and c["change"] == "modified" and c["name"] in owners)]
    order = {"removed": 0, "renamed": 1, "signature": 2, "modified": 3, "added": 4}
    changes.sort(key=lambda c: (order[c["change"]], c["file"] or "", c["line"] or 0))
    return changes


def _top(name):
    return name.split(".")[0]


def compute(repo, base=None, head="HEAD", atlas=None, root=None, with_coverage=True):
    atlas = atlas or {}
    settings = factsmod.scan_settings(atlas)
    classify = Classifier(settings)
    base_ref = base or gitio.default_base(repo, atlas.get("main_ref"))
    head_sha = gitio.resolve(repo, head)
    base_sha = gitio.resolve(repo, base_ref)
    mb = gitio.merge_base(repo, base_sha, head_sha)
    on_head = gitio.try_resolve(repo, "HEAD") == head_sha

    cache = {}
    bf = factsmod.build_facts(repo, mb, settings, cache, with_churn=False, keep_analysis=True)
    hf = factsmod.build_facts(repo, head_sha, settings, cache, with_churn=True,
                              with_coverage=with_coverage and on_head, keep_analysis=True)
    files = diff_files(repo, mb, head_sha, classify)
    for f in files:
        f["module"] = (hf["files"].get(f["path"]) or {}).get("module") or \
                      (bf["files"].get(f["old_path"] or f["path"]) or {}).get("module")

    # Lines by kind, and what the added source lines are.
    by_kind = collections.defaultdict(lambda: {"files": 0, "added": 0, "deleted": 0})
    for f in files:
        k = by_kind[f["kind"]]
        k["files"] += 1
        k["added"] += f["added"]
        k["deleted"] += f["deleted"]
    code_paths = [f["path"] for f in files if f["kind"] in ("source", "test") and f["status"] != "D" and not f["binary"]]
    added, removed = added_lines(repo, mb, head_sha, code_paths)
    breakdown = collections.Counter()
    per_file_breakdown = {}
    for f in files:
        if f["kind"] != "source" or f["path"] not in added:
            continue
        docs = (hf["_analysis"].get(f["path"]) or {}).get("docstrings", ())
        c = collections.Counter(langs.classify_line(f["lang"], text, n, docs) for n, text in added[f["path"]])
        per_file_breakdown[f["path"]] = dict(c)
        breakdown.update(c)

    # Tests added, removed and skipped.
    tests = {"added": 0, "removed": 0, "skipped_added": [], "files": {}}
    for f in files:
        if f["kind"] != "test":
            continue
        n_add = n_rem = 0
        if f["lang"] == "python":
            hs = {s["name"] for s in (hf["_analysis"].get(f["path"]) or {}).get("symbols", []) if s["kind"] != "class" and TEST_FN.search(s["name"])}
            bs = {s["name"] for s in (bf["_analysis"].get(f["old_path"] or f["path"]) or {}).get("symbols", []) if s["kind"] != "class" and TEST_FN.search(s["name"])}
            n_add, n_rem = len(hs - bs), len(bs - hs)
        else:
            n_add = sum(1 for _, t in added.get(f["path"], []) if JS_TEST_CALL.search(t))
            n_rem = sum(1 for t in removed.get(f["path"], []) if JS_TEST_CALL.search(t))
        for n, t in added.get(f["path"], []):
            if SKIP_MARK.search(t):
                tests["skipped_added"].append({"path": f["path"], "line": n, "text": t.strip()[:160]})
        tests["added"] += n_add
        tests["removed"] += n_rem
        tests["files"][f["path"]] = {"added": n_add, "removed": n_rem}

    # Module status and symbol changes.
    bm, hm = bf["modules"], hf["modules"]
    touched = collections.defaultdict(lambda: {"files": [], "added": 0, "deleted": 0})
    for f in files:
        for mid in {f["module"], (bf["files"].get(f["old_path"] or f["path"]) or {}).get("module")}:
            if mid:
                t = touched[mid]
                t["files"].append(f["path"])
                t["added"] += f["added"]
                t["deleted"] += f["deleted"]
    modules = {}
    breaking, behaviour = {}, {}
    for mid, t in sorted(touched.items()):
        if mid not in bm:
            status = "new"
        elif mid not in hm:
            status = "deleted"
        else:
            status = "changed"
        entry = {"status": status, "files": sorted(set(t["files"])), "added": t["added"], "deleted": t["deleted"], "symbols": []}
        if status == "changed":
            entry["symbols"] = symbol_changes(bm[mid], hm[mid], bf["_texts"], hf["_texts"], bm[mid]["files"], hm[mid]["files"])
            breaking[mid] = {_top(c.get("from") or c["name"]) for c in entry["symbols"] if c["change"] in ("removed", "renamed", "signature")} | \
                            {c.get("from") or c["name"] for c in entry["symbols"] if c["change"] in ("removed", "renamed", "signature")}
            behaviour[mid] = {c["name"] for c in entry["symbols"] if c["change"] == "modified"} | \
                             {_top(c["name"]) for c in entry["symbols"] if c["change"] == "modified"}
            if hm[mid]["kind"] == "config":
                entry["symbols"] = []
        elif status == "new":
            entry["symbols"] = [{"name": s["name"], "kind": s["kind"], "change": "added", "line": s["line"],
                                 "file": s.get("file"), "complexity": [None, s.get("complexity")]} for s in hm[mid]["symbols"]]
        modules[mid] = entry

    # Config keys whose value changed, and who reads them.
    config_changes = []
    for key in sorted(set(bf["config_keys"]) | set(hf["config_keys"])):
        old, new = bf["config_keys"].get(key, {}), hf["config_keys"].get(key, {})
        for path in sorted(set(old) | set(new)):
            if old.get(path) != new.get(path):
                readers = sorted(m for m, info in hm.items() if key in info["config_reads"])
                config_changes.append({"key": key, "file": path, "old": old.get(path), "new": new.get(path), "readers": readers})

    # Indirect impact: callers that use changed symbols, and readers of changed config.
    affected = collections.defaultdict(list)
    for caller, info in hm.items():
        if caller in modules:
            continue
        for target, names in info["imports"].items():
            if target not in modules or modules[target]["status"] != "changed" or hm.get(target, {}).get("kind") == "config":
                continue
            if names is None:
                if breaking.get(target) or behaviour.get(target):
                    affected[caller].append({"level": "maybe", "module": target, "reason": "imports", "names": []})
                continue
            hit_b = sorted(set(names) & breaking.get(target, set()))
            hit_m = sorted(set(names) & behaviour.get(target, set()))
            if hit_b:
                affected[caller].append({"level": "breaking", "module": target, "reason": "uses-changed-api", "names": hit_b})
            elif hit_m:
                affected[caller].append({"level": "behaviour", "module": target, "reason": "uses-modified", "names": hit_m})
    for change in config_changes:
        for reader in change["readers"]:
            if reader not in modules:
                affected[reader].append({"level": "behaviour", "module": change["file"], "reason": "reads-config",
                                         "names": [change["key"]], "old": change["old"], "new": change["new"]})
    for mid, reasons in affected.items():
        modules[mid] = {"status": "affected", "files": [], "added": 0, "deleted": 0, "symbols": [], "reasons": reasons}

    # Dependency changes.
    b_edges = {tuple(e) for e in bf["edges"]}
    h_edges = {tuple(e) for e in hf["edges"]}
    edges_added = sorted(h_edges - b_edges)
    edges_removed = sorted(b_edges - h_edges)
    b_ext = {e for m in bm.values() for e in m["ext"]}
    h_ext = {e for m in hm.values() for e in m["ext"]}
    ext_added = sorted(h_ext - b_ext)
    ext_edges = sorted({(mid, e) for mid, m in hm.items() for e in m["ext"] if e in ext_added})

    # Structure: groups, flows and pins that the change touches.
    groups, assign = project.group_modules(list(hm) + [m for m in bm if m not in hm], atlas, granularity=hf["granularity"])
    b_group_pairs = {(assign.get(a), assign.get(b)) for a, b in b_edges}
    new_group_links = sorted({(assign.get(a), assign.get(b)) for a, b in edges_added
                              if assign.get(a) != assign.get(b) and (assign.get(a), assign.get(b)) not in b_group_pairs})
    flows = {}
    for f in atlas.get("flows", []):
        members = {m for chain in f.get("chains", []) for m in chain}
        st = [modules[m]["status"] for m in members if m in modules]
        if any(s in ("changed", "new", "deleted") for s in st):
            flows[f["id"]] = "direct"
        elif st:
            flows[f["id"]] = "indirect"
    pins = []
    if root:
        all_pins = project.load_pins(root)
        for mid in sorted(modules):
            for p in project.pins_for(mid, all_pins):
                pins.append(dict(p, module=mid, status=modules[mid]["status"]))

    commits = parse_commits(repo, "%s..%s" % (mb, head_sha))
    branch = gitio.current_branch(repo) if on_head and head == "HEAD" else head

    result = {
        "schema": SCHEMA,
        "tool": "project-atlas " + __version__,
        "branch": branch,
        "base": {"ref": base_ref, "sha": base_sha},
        "head": {"ref": head, "sha": head_sha},
        "merge_base": mb,
        "granularity": hf["granularity"],
        "commits": commits,
        "files": files,
        "lines": {"by_kind": dict(by_kind), "source_added": dict(breakdown), "source_added_by_file": per_file_breakdown},
        "tests": tests,
        "modules": modules,
        "edges": {"added": [list(e) for e in edges_added], "removed": [list(e) for e in edges_removed]},
        "external": {"added": ext_added, "removed": sorted(b_ext - h_ext), "edges": [list(e) for e in ext_edges]},
        "config": config_changes,
        "groups": {"new_links": [list(p) for p in new_group_links], "assign": assign},
        "flows": flows,
        "pins": pins,
        "head_facts": factsmod.strip_private(hf),
        "base_only_modules": {m: {k: bm[m][k] for k in ("kind", "lang", "label", "loc")} for m in bm if m not in hm},
        "warnings": sorted(set(hf["warnings"]) - set(bf["warnings"]))[:50],
    }
    return result


def baseline(repo, ref, days=90, settings=None):
    """Test-to-source ratio of recent human-written changes on `ref` (agent commits excluded)."""
    classify = Classifier(settings or {})
    out = gitio.git(repo, "log", ref, "--first-parent", "-m", "--since=%d.days" % days, "--numstat",
                    "--format=%x1e%H%x1f%B%x1f", check=False)
    commits = test = source = 0
    for rec in out.split("\x1e"):
        if "\x1f" not in rec:
            continue
        _, body, stats = (rec.split("\x1f", 2) + ["", ""])[:3]
        if re.search(r"^Agent-Session:|^Co-Authored-By:.*\bClaude\b", body, re.M | re.I):
            continue
        commits += 1
        for line in stats.strip().splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or not parts[0].isdigit():
                continue
            kind, _ = classify(parts[2])
            if kind == "test":
                test += int(parts[0])
            elif kind == "source":
                source += int(parts[0])
    return {"days": days, "commits": commits, "test_added": test, "source_added": source,
            "ratio": round(test / float(source), 2) if source else None}
