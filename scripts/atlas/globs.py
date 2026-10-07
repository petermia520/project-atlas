"""Glob matching with `**`, `*`, `?`, `[...]` and `{a,b}`, against repo-relative paths.

A pattern without a slash matches at any depth (`*.py` == `**/*.py`), like .gitignore.
"""

import functools
import re


def _translate(pat):
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == n:
            out.append("(?:/.*)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
        elif c == "{":
            depth, j = 0, i
            while j < n:
                if pat[j] == "{":
                    depth += 1
                elif pat[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                parts, depth, start = [], 0, i + 1
                for k in range(i + 1, j):
                    if pat[k] == "{":
                        depth += 1
                    elif pat[k] == "}":
                        depth -= 1
                    elif pat[k] == "," and depth == 0:
                        parts.append(pat[start:k])
                        start = k + 1
                parts.append(pat[start:j])
                out.append("(?:" + "|".join(_translate(p) for p in parts) + ")")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=4096)
def compile_glob(pattern):
    pat = pattern.strip()
    if pat.startswith("./"):
        pat = pat[2:]
    if pat.startswith("/"):
        pat = pat[1:]
    elif "/" not in pat.rstrip("/"):
        pat = "**/" + pat
    if pat.endswith("/"):
        pat += "**"
    return re.compile(_translate(pat))


def match(path, pattern):
    return compile_glob(pattern).fullmatch(path) is not None


def match_any(path, patterns):
    return any(match(path, p) for p in patterns or ())
