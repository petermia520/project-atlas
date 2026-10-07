"""Per-language analysis: symbols, imports, docstrings, and line classification.

Python uses the real `ast` module. JavaScript/TypeScript use regular expressions and are
marked `approx`. Other languages get line counts only; add an analyzer to ANALYZERS to
support them.
"""

import ast
import hashlib
import json
import posixpath
import re
import sys

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "bisect", "builtins", "calendar", "collections",
    "concurrent", "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal", "difflib",
    "email", "enum", "errno", "functools", "gc", "getpass", "glob", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "logging", "math",
    "mimetypes", "multiprocessing", "numbers", "operator", "os", "pathlib", "pickle", "platform", "pprint",
    "queue", "random", "re", "secrets", "select", "shlex", "shutil", "signal", "socket", "sqlite3", "ssl",
    "stat", "statistics", "string", "struct", "subprocess", "sys", "tempfile", "textwrap", "threading",
    "time", "timeit", "traceback", "types", "typing", "unittest", "urllib", "uuid", "warnings", "weakref",
    "xml", "zipfile", "zlib", "__future__", "typing_extensions",
}
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "crypto", "dgram", "dns", "events", "fs", "http", "http2",
    "https", "net", "os", "path", "perf_hooks", "process", "querystring", "readline", "stream", "string_decoder",
    "timers", "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib",
}
COMMENT_PREFIX = {"python": ("#",), "ruby": ("#",), "shell": ("#",), "r": ("#",), "elixir": ("#",),
                  "sql": ("--",), "lua": ("--",), "yaml": ("#",), "toml": ("#",), "env": ("#",), "ini": (";", "#")}
C_COMMENT = ("//", "/*", "*", "*/")
IMPORT_LINE = {
    "python": re.compile(r"^\s*(?:from\s+\S+\s+)?import\s"),
    "javascript": re.compile(r"^\s*(?:import\s|export\s.*\sfrom\s|const\s+\S.*=\s*require\()"),
    "go": re.compile(r'^\s*(?:import\b|"[\w./-]+"\s*$)'),
    "java": re.compile(r"^\s*import\s"), "kotlin": re.compile(r"^\s*import\s"),
    "rust": re.compile(r"^\s*use\s"), "csharp": re.compile(r"^\s*using\s"),
}
IMPORT_LINE["typescript"] = IMPORT_LINE["javascript"]


def seg_hash(lines, start, end):
    seg = "\n".join(line.rstrip() for line in lines[start - 1:end])
    return hashlib.sha1(seg.encode("utf-8")).hexdigest()[:12]


def count_loc(text):
    return sum(1 for line in text.splitlines() if line.strip())


# ---------------------------------------------------------------- Python

_MATCH_CASE = getattr(ast, "match_case", None)


def py_complexity(node):
    score = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)):
            score += 1
        elif isinstance(n, ast.BoolOp):
            score += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            score += 1 + len(n.ifs)
        elif _MATCH_CASE is not None and isinstance(n, _MATCH_CASE):
            score += 1
    return score


def _py_sig(node):
    try:
        sig = "(" + ast.unparse(node.args) + ")"
        if node.returns is not None:
            sig += " -> " + ast.unparse(node.returns)
        return sig
    except AttributeError:  # Python < 3.9
        return "(" + ", ".join(a.arg for a in node.args.args) + ")"


def analyze_python(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return {"symbols": [], "imports": [], "attrs": {}, "docstrings": [],
                "error": "syntax error at line %s" % getattr(exc, "lineno", "?")}
    lines = text.splitlines()
    symbols = []

    def visit(body, prefix):
        for n in body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = min([n.lineno] + [d.lineno for d in n.decorator_list])
            end = getattr(n, "end_lineno", None) or n.lineno
            sym = {"name": prefix + n.name, "line": start, "end": end, "hash": seg_hash(lines, start, end)}
            if isinstance(n, ast.ClassDef):
                sym["kind"] = "class"
                symbols.append(sym)
                visit(n.body, prefix + n.name + ".")
            else:
                sym["kind"] = "method" if prefix else "function"
                sym["sig"] = _py_sig(n)
                sym["complexity"] = py_complexity(n)
                symbols.append(sym)

    visit(tree.body, "")

    docstrings = []
    for n in [tree] + [x for x in ast.walk(tree) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        body = getattr(n, "body", None) or []
        first = body[0] if body else None
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                and isinstance(first.value.value, str):
            docstrings.append([first.lineno, getattr(first, "end_lineno", first.lineno)])

    imports = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imports.append({"kind": "import", "module": a.name, "level": 0, "line": n.lineno,
                                "alias": a.asname, "dotted": "." in a.name})
        elif isinstance(n, ast.ImportFrom):
            imports.append({"kind": "from", "module": n.module or "", "level": n.level or 0, "line": n.lineno,
                            "names": [[a.name, a.asname or a.name] for a in n.names]})

    bound = set()
    for imp in imports:
        if imp["kind"] == "import":
            bound.add(imp["alias"] or imp["module"].split(".")[0])
        else:
            bound.update(alias for _, alias in imp["names"])
    attrs = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in bound:
            attrs.setdefault(n.value.id, set()).add(n.attr)
    return {"symbols": symbols, "imports": imports, "attrs": {k: sorted(v) for k, v in attrs.items()},
            "docstrings": docstrings}


def py_module_name(path, roots):
    if not path.endswith((".py", ".pyi")):
        return None
    for root in roots:
        if root and not path.startswith(root + "/"):
            continue
        rel = path[len(root) + 1:] if root else path
        parts = rel.rsplit(".", 1)[0].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts):
            return ".".join(parts)
    return None


class PythonIndex:
    """Maps dotted module names to files so imports can be resolved to repo paths."""

    def __init__(self, paths, roots):
        self.roots = sorted(roots, key=len, reverse=True)
        self.by_name, self.name_of = {}, {}
        for p in sorted(paths):
            name = py_module_name(p, self.roots)
            if name and name not in self.by_name:
                self.by_name[name] = p
                self.name_of[p] = name
        self.tops = {n.split(".")[0] for n in self.by_name}

    def longest(self, dotted):
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            hit = self.by_name.get(".".join(parts[:i]))
            if hit:
                return hit
        return None

    def resolve(self, path, analysis):
        """({target_path: set(names) | None}, {external_top_level_names})"""
        internal, external = {}, set()
        attrs = analysis.get("attrs", {})
        me = self.name_of.get(path) or py_module_name(path, self.roots) or ""
        pkg = me.split(".") if me else []
        if not path.endswith("__init__.py") and pkg:
            pkg = pkg[:-1]

        def add(target, names):
            if not target or target == path:
                return
            if target in internal and (internal[target] is None or names is None):
                internal[target] = None
            elif target in internal:
                internal[target] |= names
            else:
                internal[target] = None if names is None else set(names)

        def used(alias):
            got = attrs.get(alias)
            return set(got) if got else None

        def external_top(dotted):
            top = dotted.split(".")[0]
            if top and top not in STDLIB and top not in self.tops:
                external.add(top)

        for imp in analysis.get("imports", []):
            if imp["kind"] == "import":
                target = self.longest(imp["module"])
                if target:
                    names = used(imp["alias"]) if imp["alias"] else (None if imp["dotted"] else used(imp["module"]))
                    add(target, names)
                else:
                    external_top(imp["module"])
                continue
            if imp["level"]:
                keep = len(pkg) - (imp["level"] - 1)
                base = pkg[:keep] if keep >= 0 else []
                full = ".".join(base + ([imp["module"]] if imp["module"] else []))
            else:
                full = imp["module"]
            for name, alias in imp["names"]:
                if name == "*":
                    add(self.by_name.get(full), None)
                    continue
                sub = (full + "." + name) if full else name
                if sub in self.by_name:
                    add(self.by_name[sub], used(alias))
                elif full and self.longest(full):
                    add(self.longest(full), {name})
                elif not imp["level"]:
                    external_top(full or name)
        return internal, external


# ---------------------------------------------------------------- JavaScript / TypeScript

JS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"]
_JS_FROM = re.compile(r"""\bimport\s+(?:type\s+)?([\w$\s{},*]+?)\s+from\s*['"]([^'"\n]+)['"]""")
_JS_BARE = re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]""")
_JS_EXPORT = re.compile(r"""\bexport\s+(?:type\s+)?(\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s*from\s*['"]([^'"\n]+)['"]""")
_JS_REQUIRE = re.compile(r"""\brequire\s*\(\s*['"]([^'"\n]+)['"]\s*\)""")
_JS_DYNAMIC = re.compile(r"""\bimport\s*\(\s*['"]([^'"\n]+)['"]\s*\)""")
_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_JS_LINE_COMMENT = re.compile(r"(^|[^:\\])//[^\n]*")
_JS_SYMBOLS = [
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)\s*(\([^)]*\))", re.M), "function"),
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([\w$]+)", re.M), "class"),
    (re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=\n]+)?=\s*(?:async\s+)?(\([^)]*\)|[\w$]+)\s*(?::[^=\n]+)?=>", re.M), "function"),
]
_JS_BRANCH = re.compile(r"\b(?:if|for|while|case|catch)\b|\?\?|&&|\|\||\?(?=[^.:?])")


def _js_names(clause):
    clause = clause.strip()
    if "*" in clause:
        return None
    names = set()
    m = re.search(r"\{([^}]*)\}", clause)
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if part.startswith("type "):
                part = part[5:]
            if part:
                names.add(re.split(r"\s+as\s+", part)[0].strip())
    default = clause.split("{")[0].strip().rstrip(",").strip()
    if default:
        names.add("default")
    return names or None


def _block_end(text, start, arrow=False):
    """1-based line where the {...} body that starts after `start` closes."""
    line_end = text.find("\n", start)
    line_end = len(text) if line_end == -1 else line_end
    if arrow and not text[start:line_end].lstrip().startswith("{"):
        return text.count("\n", 0, start) + 1
    i = text.find("{", start)
    if i == -1:
        return text.count("\n", 0, start) + 1
    depth, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text.count("\n", 0, i) + 1
        i += 1
    return text.count("\n") + 1


def analyze_js(text):
    stripped = _JS_LINE_COMMENT.sub(r"\1", _JS_BLOCK_COMMENT.sub("", text))
    imports = []
    for m in _JS_FROM.finditer(stripped):
        imports.append({"spec": m.group(2), "names": _js_names(m.group(1))})
    for rx in (_JS_BARE, _JS_REQUIRE, _JS_DYNAMIC):
        for m in rx.finditer(stripped):
            imports.append({"spec": m.group(1), "names": None})
    for m in _JS_EXPORT.finditer(stripped):
        imports.append({"spec": m.group(2), "names": _js_names(m.group(1))})
    for imp in imports:
        if isinstance(imp["names"], set):
            imp["names"] = sorted(imp["names"])
    lines = text.splitlines()
    symbols = []
    for rx, kind in _JS_SYMBOLS:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            end = _block_end(text, m.end(), arrow=rx is _JS_SYMBOLS[2][0])
            seg = "\n".join(lines[line - 1:end])
            sym = {"name": m.group(1), "kind": kind, "line": line, "end": max(end, line),
                   "hash": seg_hash(lines, line, max(end, line))}
            if kind == "function":
                sym["sig"] = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                sym["complexity"] = 1 + len(_JS_BRANCH.findall(seg))
            symbols.append(sym)
    symbols.sort(key=lambda s: s["line"])
    return {"symbols": symbols, "imports": imports, "docstrings": [], "approx": True}


def load_ts_aliases(text):
    """[(prefix, target_dir)] from tsconfig compilerOptions.paths (best effort)."""
    if not text:
        return []
    try:
        cfg = json.loads(re.sub(r"(^|\s)//[^\n]*", r"\1", _JS_BLOCK_COMMENT.sub("", text)))
    except ValueError:
        return []
    opts = cfg.get("compilerOptions") or {}
    base = (opts.get("baseUrl") or ".").strip("./")
    out = []
    for key, targets in (opts.get("paths") or {}).items():
        if not targets:
            continue
        prefix = key.rstrip("*")
        target = posixpath.normpath(posixpath.join(base, targets[0].rstrip("*")))
        out.append((prefix, "" if target == "." else target.rstrip("/") + "/"))
    return sorted(out, key=lambda x: len(x[0]), reverse=True)


def resolve_js(path, spec, files, aliases=()):
    """('internal', path) | ('external', package) | ('builtin', spec) | ('unresolved', spec)"""
    base = None
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
    else:
        for prefix, target in aliases:
            if spec.startswith(prefix):
                base = posixpath.normpath(target + spec[len(prefix):])
                break
    if base is not None:
        cands = [base] + [base + e for e in JS_EXTS] + [base + "/index" + e for e in JS_EXTS]
        if base.endswith((".js", ".jsx", ".mjs")):
            stem = base.rsplit(".", 1)[0]
            cands += [stem + e for e in (".ts", ".tsx", ".mts")]
        for c in cands:
            if c in files:
                return "internal", c
        return "unresolved", spec
    if spec.startswith("node:") or spec.split("/")[0] in NODE_BUILTINS:
        return "builtin", spec
    parts = spec.split("/")
    return "external", "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


ANALYZERS = {"python": analyze_python, "javascript": analyze_js, "typescript": analyze_js}


def analyze(lang, text):
    fn = ANALYZERS.get(lang)
    return fn(text) if fn else None


# ---------------------------------------------------------------- line classification

def classify_line(lang, line, lineno=None, docstrings=()):
    """blank | comment | docstring | import | logic"""
    s = line.strip()
    if not s:
        return "blank"
    if lineno is not None:
        for a, b in docstrings:
            if a <= lineno <= b:
                return "docstring"
    prefixes = COMMENT_PREFIX.get(lang, C_COMMENT)
    if s.startswith(prefixes):
        return "comment"
    rx = IMPORT_LINE.get(lang)
    if rx and rx.match(line):
        return "import"
    return "logic"


# ---------------------------------------------------------------- config keys

def _flatten(obj, prefix, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, (prefix + "." if prefix else "") + str(k), out)
    elif prefix:
        out[prefix] = json.dumps(obj, ensure_ascii=False) if isinstance(obj, (list, bool)) or obj is None else str(obj)


_YAML_KEY = re.compile(r"^(\s*)(?:-\s+)?([\"']?)([A-Za-z0-9_.\-/]+)\2\s*:(?:\s+(.*?))?\s*$")


def _yaml_keys(text):
    """Leaf key paths of a YAML mapping (no PyYAML needed; lists and anchors are ignored)."""
    out, stack = {}, []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith(("#", "---", "...")):
            continue
        m = _YAML_KEY.match(raw)
        if not m or raw.lstrip().startswith("- "):
            continue
        indent, key, value = len(m.group(1)), m.group(3), (m.group(4) or "")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([k for _, k in stack] + [key])
        value = value.split(" #", 1)[0].strip().strip("'\"")
        if value and value not in ("|", ">", "|-", ">-"):
            out[path] = value
        else:
            stack.append((indent, key))
    return out


def _ini_keys(text):
    out, section = {}, ""
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith(("#", ";")):
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip()
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            out[(section + "." if section else "") + k.strip()] = v.strip()
        elif ":" in s:
            k, v = s.split(":", 1)
            out[(section + "." if section else "") + k.strip()] = v.strip()
    return out


def _env_keys(text):
    out = {}
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("export "):
            s = s[7:]
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k.strip()):
            out[k.strip()] = v.strip().strip("'\"")
    return out


def config_keys(path, text):
    """{dotted.key: value} for a config file; {} when it cannot be parsed."""
    lang = None
    ext = posixpath.splitext(path)[1]
    base = posixpath.basename(path)
    if ext in (".yaml", ".yml"):
        lang = "yaml"
    elif ext == ".json":
        lang = "json"
    elif ext == ".toml":
        lang = "toml"
    elif ext in (".ini", ".cfg", ".properties", ".conf"):
        lang = "ini"
    elif base.startswith(".env") or ext == ".env":
        lang = "env"
    out = {}
    try:
        if lang == "yaml":
            out = _yaml_keys(text)
        elif lang == "json":
            _flatten(json.loads(text), "", out)
        elif lang == "toml" and tomllib is not None:
            _flatten(tomllib.loads(text), "", out)
        elif lang in ("ini", "toml"):
            out = _ini_keys(text)
        elif lang == "env":
            out = _env_keys(text)
    except Exception:  # malformed config: skip it, facts stay usable
        return {}
    return {k: (v if len(v) <= 120 else v[:117] + "...") for k, v in out.items()}


def key_reader_regex(key, is_env=False):
    """A regex that finds code reading `key`, or None for keys too generic to search."""
    parts = key.split(".")
    leaf = parts[-1]
    if len(leaf) < 3:
        return None
    alts = [r"""['"`]%s['"`]""" % re.escape(key)] if len(parts) > 1 or is_env else []
    if is_env:
        alts.append(r"\benv\.%s\b" % re.escape(key))
    if len(parts) >= 2:
        a, b = re.escape(parts[-2]), re.escape(leaf)
        alts.append(r"\.%s\.%s\b" % (a, b))
        alts.append(r"""\[\s*['"]%s['"]\s*\]\s*\[\s*['"]%s['"]\s*\]""" % (a, b))
        alts.append(r"""\.get\(\s*['"]%s['"][^)]*\)\s*\.get\(\s*['"]%s['"]""" % (a, b))
        alts.append(r"""['"]%s\.%s['"]""" % (a, b))
    if not alts:
        return None
    return re.compile("|".join(alts))
