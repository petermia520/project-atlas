"""Facts about one revision: modules, symbols, dependencies, config readers, owners, churn.

The output is deterministic for a given commit and settings, so it can be regenerated
after every merge without review.
"""

import collections
import datetime
import hashlib
import os
import posixpath
import re
import xml.etree.ElementTree as ET

from . import SCHEMA, __version__, gitio, globs, langs
from .classify import Classifier

DEFAULT_SCAN = {
    "granularity": "auto",       # file | dir | auto
    "max_file_modules": 150,     # auto switches to directory modules above this many source files
    "dir_depth": None,           # directory modules: how many path segments deep (default 3, or 2 if that is still too many)
    "max_dir_modules": 250,
    "include": [],
    "exclude": [],
    "classify": {},              # {kind: [globs]} checked before the built-in rules
    "python_roots": None,        # e.g. ["src"]; default tries "", src, lib
    "coverage_files": ["coverage.xml", "coverage/cobertura-coverage.xml", "lcov.info", "coverage/lcov.info"],
    "max_bytes": 1000000,
}
ANALYZED_KINDS = ("source", "test")


def scan_settings(atlas):
    settings = dict(DEFAULT_SCAN)
    settings.update((atlas or {}).get("scan") or {})
    return settings


def _codeowners(text):
    rules = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        pat = parts[0]
        if pat.endswith("/"):
            pat += "**"
        elif "/" not in pat.rstrip("/") and "*" not in pat and "." not in pat:
            pat = pat + "/**" if not pat.startswith("/") else pat
        rules.append((pat, [p for p in parts[1:] if p.startswith("@") or "@" in p]))
    return rules


def _owners_for(path, rules):
    owners = []
    for pat, who in rules:
        if globs.match(path, pat) or globs.match(path, pat.rstrip("*").rstrip("/") + "/**"):
            owners = who
    return owners


def _coverage(repo, files, patterns):
    """{path: percent} from Cobertura XML or LCOV files in the working tree."""
    tracked = set(files)
    by_suffix = collections.defaultdict(list)
    for p in tracked:
        by_suffix[posixpath.basename(p)].append(p)

    def match(name):
        name = name.replace("\\", "/").lstrip("./")
        if name in tracked:
            return name
        for cand in by_suffix.get(posixpath.basename(name), []):
            if cand.endswith(name) or name.endswith(cand):
                return cand
        return None

    out = {}
    for pat in patterns:
        path = os.path.join(repo, pat)
        if not os.path.isfile(path):
            continue
        try:
            if path.endswith(".xml"):
                root = ET.parse(path).getroot()
                for cls in root.iter("class"):
                    hit = match(cls.get("filename", ""))
                    if hit and cls.get("line-rate") is not None:
                        out[hit] = round(float(cls.get("line-rate")) * 100, 1)
            else:
                current, lf, lh = None, 0, 0
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("SF:"):
                            current, lf, lh = match(line[3:]), 0, 0
                        elif line.startswith("LF:"):
                            lf = int(line[3:] or 0)
                        elif line.startswith("LH:"):
                            lh = int(line[3:] or 0)
                        elif line == "end_of_record" and current and lf:
                            out[current] = round(100.0 * lh / lf, 1)
        except (ET.ParseError, ValueError, OSError):
            continue
    return out


def _churn(repo, rev, days=30):
    out = gitio.git(repo, "log", "--since=%d.days" % days, "--format=", "--name-only", rev, check=False)
    return collections.Counter(line for line in out.splitlines() if line.strip())


def _manifest_versions(texts):
    """{package_name_lower: version_spec} from package.json, pyproject.toml and requirements files."""
    out = {}
    for path, text in texts.items():
        base = posixpath.basename(path)
        try:
            if base == "package.json":
                import json
                data = json.loads(text)
                for sec in ("dependencies", "devDependencies", "peerDependencies"):
                    for k, v in (data.get(sec) or {}).items():
                        out.setdefault(k.lower(), str(v))
            elif base.startswith("requirements") and base.endswith(".txt"):
                for line in text.splitlines():
                    m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*([<>=!~].*)?$", line.split("#")[0])
                    if m:
                        out.setdefault(m.group(1).lower(), (m.group(2) or "").strip())
            elif base == "pyproject.toml":
                for m in re.finditer(r"""['"]([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*([<>=!~][^'"]*)?['"]""", text):
                    out.setdefault(m.group(1).lower(), (m.group(3) or "").strip())
        except ValueError:
            continue
    return out


def module_label(mid, kind, granularity):
    if mid == ".":
        return "(root)"
    base = posixpath.basename(mid)
    if kind == "config" or granularity == "dir":
        return base + ("/" if granularity == "dir" and kind != "config" else "")
    stem = base.rsplit(".", 1)[0] if "." in base else base
    if stem in ("__init__", "index", "mod", "main"):
        parent = posixpath.basename(posixpath.dirname(mid))
        return (parent + "/" + stem) if parent else stem
    return stem


def build_facts(repo, rev, settings=None, cache=None, with_churn=True, with_coverage=False, keep_analysis=False):
    """Facts for `rev`. `cache` (dict) shares per-blob analysis between calls."""
    settings = dict(DEFAULT_SCAN, **(settings or {}))
    cache = {} if cache is None else cache
    classify = Classifier(settings)
    warnings = []
    files, texts = {}, {}
    with gitio.TreeReader(repo, rev) as tree:
        sha = tree.rev
        entries = tree.entries()
        for path, blob, size in entries:
            kind, lang = classify(path)
            if kind is None:
                continue
            files[path] = {"kind": kind, "lang": lang, "sha": blob, "size": size}
        for path, f in files.items():
            if f["kind"] not in ("source", "test", "config", "manifest"):
                continue
            if f["size"] > settings["max_bytes"]:
                warnings.append("skipped large file %s (%d bytes)" % (path, f["size"]))
                continue
            text = gitio.decode(tree.read(path))
            if text is None:
                continue
            texts[path] = text
            f["loc"] = langs.count_loc(text)
        owners_text = None
        for cand in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            owners_text = gitio.decode(tree.read(cand))
            if owners_text:
                break
        ts_aliases = langs.load_ts_aliases(gitio.decode(tree.read("tsconfig.json")))

    # Per-file analysis, shared across revisions by blob id.
    analysis = {}
    for path, text in texts.items():
        f = files[path]
        if f["kind"] not in ANALYZED_KINDS or f["lang"] not in langs.ANALYZERS:
            continue
        key = (f["sha"], f["lang"])
        if key not in cache:
            cache[key] = langs.analyze(f["lang"], text)
        analysis[path] = cache[key]
        if analysis[path].get("error"):
            warnings.append("%s: %s" % (path, analysis[path]["error"]))

    source = sorted(p for p, f in files.items() if f["kind"] == "source")
    granularity = settings["granularity"]
    if granularity == "auto":
        granularity = "file" if len(source) <= settings["max_file_modules"] else "dir"
    depth = settings.get("dir_depth")
    if granularity == "dir" and not depth:
        depth = 3
        if len({"/".join(posixpath.dirname(p).split("/")[:3]) for p in source}) > settings["max_dir_modules"]:
            depth = 2

    def module_of(path):
        f = files.get(path)
        if not f:
            return None
        if f["kind"] == "config":
            return path
        if f["kind"] != "source" or f.get("loc") == 0:  # empty __init__.py and friends are not modules
            return None
        if granularity == "file":
            return path
        return "/".join((posixpath.dirname(path) or ".").split("/")[:depth])

    for path, f in files.items():
        mid = module_of(path)
        if mid:
            f["module"] = mid

    roots = settings.get("python_roots")
    if roots is None:
        roots = [""] + [r for r in ("src", "lib", "python") if any(p.startswith(r + "/") for p in files)]
    py_paths = [p for p, f in files.items() if f["lang"] == "python" and f["kind"] in ANALYZED_KINDS]
    pyindex = langs.PythonIndex(py_paths, roots)
    js_files = {p for p, f in files.items() if f["lang"] in ("javascript", "typescript")}

    owner_rules = _codeowners(owners_text)
    churn = _churn(repo, sha) if with_churn else {}
    coverage = _coverage(repo, list(files), settings["coverage_files"]) if with_coverage else {}

    modules = {}

    def module(mid):
        if mid not in modules:
            kind = files[mid]["kind"] if mid in files and files[mid]["kind"] == "config" else "source"
            modules[mid] = {"kind": kind, "lang": None, "label": module_label(mid, kind, granularity),
                            "files": [], "loc": 0, "symbols": [], "imports": {}, "ext": set(),
                            "config_reads": set(), "owners": set(), "churn30": 0, "_cov": [], "_hash": []}
        return modules[mid]

    def link(src, dst, names):
        if not dst or dst == src:
            return
        imports = modules[src]["imports"]
        if dst in imports and (imports[dst] is None or names is None):
            imports[dst] = None
        elif dst in imports:
            imports[dst] |= set(names)
        else:
            imports[dst] = None if names is None else set(names)

    for path in sorted(files):
        mid = module_of(path)
        if not mid:
            continue
        f, m = files[path], module(mid)
        m["files"].append(path)
        m["loc"] += f.get("loc", 0)
        m["lang"] = m["lang"] or f["lang"]
        m["owners"].update(_owners_for(path, owner_rules))
        m["churn30"] += churn.get(path, 0)
        m["_hash"].append(path + ":" + f["sha"])
        if path in coverage:
            m["_cov"].append((coverage[path], f.get("loc", 0)))
        a = analysis.get(path)
        if not a:
            continue
        for s in a["symbols"]:
            sym = dict(s)
            if granularity == "dir":
                sym["file"] = path
            m["symbols"].append(sym)
        if f["lang"] == "python":
            internal, external = pyindex.resolve(path, a)
            for target, names in internal.items():
                link(mid, module_of(target), names)
            m["ext"].update(external)
        else:
            for imp in a["imports"]:
                kind, target = langs.resolve_js(path, imp["spec"], js_files, ts_aliases)
                if kind == "internal":
                    link(mid, module_of(target), imp["names"])
                elif kind == "external":
                    m["ext"].add(target)

    # Config keys and the source modules that read them.
    config_keys = {}
    for path, f in files.items():
        if f["kind"] == "config" and path in texts:
            keys = langs.config_keys(path, texts[path])
            if len(keys) > 1500:
                warnings.append("skipped config keys of %s (%d keys; looks like data, not settings)" % (path, len(keys)))
                continue
            for key, value in keys.items():
                config_keys.setdefault(key, {})[path] = value
    readers = []
    for key, where in config_keys.items():
        is_env = all(f.endswith(".env") or posixpath.basename(f).startswith(".env") for f in where)
        rx = langs.key_reader_regex(key, is_env)
        if rx:
            readers.append((key, key.split(".")[-1], rx, sorted(where)))
    for path in source:
        text = texts.get(path)
        mid = module_of(path)
        if not text or not mid:
            continue
        for key, needle, rx, where in readers:
            if needle in text and rx.search(text):
                modules[mid]["config_reads"].add(key)
                for cfg in where:
                    link(mid, cfg, {key})

    versions = _manifest_versions({p: t for p, t in texts.items() if files[p]["kind"] == "manifest"})
    ext_usage = collections.Counter()
    for m in modules.values():
        ext_usage.update(m["ext"])

    edges = []
    for mid, m in sorted(modules.items()):
        cov = m.pop("_cov")
        total = sum(loc for _, loc in cov)
        m["coverage"] = round(sum(c * loc for c, loc in cov) / total, 1) if total else None
        m["hash"] = hashlib.sha1("\n".join(sorted(m.pop("_hash"))).encode()).hexdigest()[:16]
        m["imports"] = {k: (sorted(v) if v is not None else None) for k, v in sorted(m["imports"].items())}
        m["ext"] = sorted(m["ext"])
        m["config_reads"] = sorted(m["config_reads"])
        m["owners"] = sorted(m["owners"])
        m["symbols"].sort(key=lambda s: (s.get("file", ""), s["line"]))
        edges.extend([mid, dst] for dst in m["imports"])

    kinds = collections.Counter(f["kind"] for f in files.values())
    facts = {
        "schema": SCHEMA,
        "tool": "project-atlas " + __version__,
        "rev": sha,
        "rev_date": gitio.commit_date(repo, sha),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "granularity": granularity,
        "dir_depth": depth if granularity == "dir" else None,
        "counts": dict(sorted(kinds.items())),
        "files": {p: {k: f[k] for k in ("kind", "lang", "loc", "module") if f.get(k) is not None}
                  for p, f in sorted(files.items()) if f["kind"] in ("source", "test", "config", "manifest", "fixture")},
        "modules": modules,
        "edges": edges,
        "config_keys": {k: dict(sorted(v.items())) for k, v in sorted(config_keys.items())},
        "external": {name: {"modules": n, "version": versions.get(name.lower(), versions.get(name.lower().replace("_", "-")))}
                     for name, n in sorted(ext_usage.items())},
        "warnings": warnings[:200],
    }
    if keep_analysis:
        facts["_analysis"] = analysis
        facts["_texts"] = texts
    return facts


def strip_private(facts):
    return {k: v for k, v in facts.items() if not k.startswith("_")}


def reverse_edges(facts):
    rev = collections.defaultdict(list)
    for a, b in facts["edges"]:
        rev[b].append(a)
    return rev


def summary(facts, max_modules=250):
    """A compact text overview an agent can read before proposing groups and flows."""
    mods = facts["modules"]
    rev = reverse_edges(facts)
    lines = [
        "rev %s · granularity %s · %d modules · %d edges" % (gitio.short(facts["rev"]), facts["granularity"], len(mods), len(facts["edges"])),
        "files by kind: " + ", ".join("%s %d" % kv for kv in facts["counts"].items()),
        "",
        "## Directories (modules, lines of code, outgoing edges to other directories)",
    ]
    by_dir = collections.defaultdict(lambda: [0, 0, collections.Counter()])
    def top(mid):
        parts = mid.split("/")
        return "/".join(parts[:2]) if len(parts) > 2 else parts[0]
    for mid, m in mods.items():
        d = by_dir[top(mid)]
        d[0] += 1
        d[1] += m["loc"]
        for dst in m["imports"]:
            if top(dst) != top(mid):
                d[2][top(dst)] += 1
    for name, (n, loc, out) in sorted(by_dir.items()):
        targets = ", ".join("%s×%d" % kv for kv in out.most_common(6))
        lines.append("- %s: %d modules, %d loc%s" % (name, n, loc, (" → " + targets) if targets else ""))
    lines += ["", "## Modules (id · loc · in/out edges · main symbols)"]
    for mid, m in sorted(mods.items())[:max_modules]:
        syms = [s["name"] for s in m["symbols"] if s["kind"] != "method"][:6]
        extra = (" · reads " + ", ".join(m["config_reads"][:4])) if m["config_reads"] else ""
        lines.append("- %s · %d · in %d / out %d · %s%s" % (mid, m["loc"], len(rev.get(mid, [])), len(m["imports"]),
                                                          ", ".join(syms) or "-", extra))
    if len(mods) > max_modules:
        lines.append("... %d more modules (see map.json)" % (len(mods) - max_modules))
    if facts["external"]:
        lines += ["", "## External packages (used by N modules)",
                  ", ".join("%s(%d)" % (k, v["modules"]) for k, v in sorted(facts["external"].items(), key=lambda kv: -kv[1]["modules"])[:40])]
    if facts["config_keys"]:
        lines += ["", "## Config keys read by code"]
        readers = collections.defaultdict(list)
        for mid, m in mods.items():
            for k in m["config_reads"]:
                readers[k].append(mid)
        for k, who in sorted(readers.items(), key=lambda kv: -len(kv[1]))[:30]:
            lines.append("- %s: %d readers" % (k, len(who)))
    if facts["warnings"]:
        lines += ["", "## Warnings"] + ["- " + w for w in facts["warnings"][:20]]
    return "\n".join(lines)
