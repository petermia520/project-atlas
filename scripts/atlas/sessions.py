"""Agent sessions behind a branch.

Sources, strongest first:
  1. commit trailers   `Agent-Session: <id>` (+ Agent-Decision / Agent-Assumption)  - shared via git
  2. git notes         refs/notes/atlas-sessions (opt-in, written by the SessionEnd hook) - shared once pushed
  3. local summaries   <git-common-dir>/atlas/sessions/<id>.json (SessionEnd hook)       - this machine
  4. raw transcripts   ~/.claude/projects/<encoded cwd>/<id>.jsonl                         - this machine, until cleanup
"""

import collections
import glob
import json
import os
import re

from . import gitio

SKIP_PREFIXES = ("<local-command", "<command-name>", "<command-message>", "<command-args>", "<system-reminder>",
                 "<bash-input>", "<bash-stdout>", "<bash-stderr>", "Caveat:")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
NOTES_REF = "atlas-sessions"


def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def encode_project_dir(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def _rel(path, cwd):
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return path


def summarize_transcript(path, max_text=400):
    """{branch: summary} for one transcript; entries are attributed to the branch they ran on."""
    per = {}
    usage_by_msg = collections.defaultdict(dict)
    session_id = os.path.splitext(os.path.basename(path))[0]

    def bucket(branch):
        if branch not in per:
            per[branch] = {"id": session_id, "branch": branch, "source": "transcript", "transcript_path": path,
                           "cwd": None, "start": None, "end": None, "task": None, "human_messages": [],
                           "interrupts": 0, "tool_calls": 0, "tools": collections.Counter(), "files_touched": set(),
                           "models": set(), "subagent_tool_calls": 0, "_msgs": set()}
        return per[branch]

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("type") not in ("user", "assistant"):
                continue
            branch = e.get("gitBranch") or "HEAD"
            s = bucket(branch)
            session_id = e.get("sessionId") or session_id
            s["id"] = session_id
            s["cwd"] = s["cwd"] or e.get("cwd")
            ts = e.get("timestamp")
            if ts:
                s["start"] = min(s["start"] or ts, ts)
                s["end"] = max(s["end"] or ts, ts)
            msg = e.get("message") or {}
            if e["type"] == "assistant":
                mid = msg.get("id")
                if mid:
                    s["_msgs"].add(mid)
                    if msg.get("usage"):
                        usage_by_msg[branch][mid] = msg["usage"]
                if msg.get("model") and not msg["model"].startswith("<"):
                    s["models"].add(msg["model"])
                for block in msg.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    if e.get("isSidechain"):
                        s["subagent_tool_calls"] += 1
                    s["tool_calls"] += 1
                    s["tools"][block.get("name", "?")] += 1
                    if block.get("name") in EDIT_TOOLS:
                        fp = (block.get("input") or {}).get("file_path") or (block.get("input") or {}).get("notebook_path")
                        if fp:
                            s["files_touched"].add(_rel(fp, s["cwd"]))
                continue
            if e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
                continue
            text = _text_of(msg.get("content"))
            if not text:
                continue
            stripped = text.strip()
            if stripped.startswith("[Request interrupted by user"):
                s["interrupts"] += 1
                continue
            if stripped.startswith(SKIP_PREFIXES):
                continue
            item = {"ts": ts, "text": stripped[:max_text] + ("…" if len(stripped) > max_text else "")}
            if s["task"] is None:
                s["task"] = stripped[:2000]
            else:
                s["human_messages"].append(item)

    out = {}
    for branch, s in per.items():
        tokens = collections.Counter()
        for usage in usage_by_msg[branch].values():
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                if isinstance(usage.get(k), int):
                    tokens[k] += usage[k]
        s["tokens"] = dict(tokens)
        s["assistant_messages"] = len(s.pop("_msgs"))
        s["tools"] = dict(s["tools"].most_common())
        s["files_touched"] = sorted(s["files_touched"])
        s["models"] = sorted(s["models"])
        s["duration_s"] = _seconds(s["start"], s["end"])
        out[branch] = s
    return out


def _seconds(a, b):
    import datetime
    try:
        fa = datetime.datetime.fromisoformat(a.replace("Z", "+00:00"))
        fb = datetime.datetime.fromisoformat(b.replace("Z", "+00:00"))
        return int((fb - fa).total_seconds())
    except (AttributeError, ValueError):
        return None


def condensed(path, max_len=300, include_tools=True):
    """A readable log of one transcript: user text, assistant text and tool calls (no thinking, no results)."""
    lines = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("type") not in ("user", "assistant") or e.get("isMeta"):
                continue
            ts = (e.get("timestamp") or "")[:19].replace("T", " ")
            side = " [subagent]" if e.get("isSidechain") else ""
            msg = e.get("message") or {}
            if e["type"] == "user":
                text = _text_of(msg.get("content"))
                if text and not text.strip().startswith(SKIP_PREFIXES):
                    lines.append("%s USER%s: %s" % (ts, side, _clip(text, max_len * 2)))
                continue
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    lines.append("%s CLAUDE%s: %s" % (ts, side, _clip(block["text"], max_len * 2)))
                elif include_tools and block.get("type") == "tool_use":
                    inp = block.get("input") or {}
                    detail = inp.get("description") or inp.get("file_path") or inp.get("command") or inp.get("pattern") or ""
                    lines.append("%s TOOL %s%s: %s" % (ts, block.get("name"), side, _clip(str(detail), max_len)))
    return "\n".join(lines)


def _clip(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def summaries_dir(repo):
    return os.path.join(gitio.common_dir(repo), "atlas", "sessions")


def _transcript_files(repo, scan_all=False):
    home = os.path.join(claude_home(), "projects")
    if not os.path.isdir(home):
        return []
    dirs = set()
    if scan_all:
        dirs.update(glob.glob(os.path.join(home, "*")))
    else:
        for wt in gitio.worktrees(repo):
            enc = encode_project_dir(os.path.realpath(wt))
            dirs.update(glob.glob(os.path.join(home, glob.escape(enc) + "*")))
            enc2 = encode_project_dir(wt)
            dirs.update(glob.glob(os.path.join(home, glob.escape(enc2) + "*")))
    files = []
    for d in sorted(dirs):
        files.extend(glob.glob(os.path.join(d, "*.jsonl")))
    return files


def find(repo, branch, base_sha, head_sha, scan_all=False):
    commits = gitio.git(repo, "log", "--format=%H%x1f%(trailers:unfold,only)%x1e", "%s..%s" % (base_sha, head_sha))
    trailers, trailer_ids = [], set()
    for rec in commits.split("\x1e"):
        rec = rec.strip("\n")
        if "\x1f" not in rec:
            continue
        sha, body = rec.split("\x1f", 1)
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = [x.strip() for x in line.split(":", 1)]
            if key.lower().startswith("agent-"):
                trailers.append({"sha": sha, "key": key, "value": value})
                if key.lower() == "agent-session":
                    trailer_ids.add(value)

    found = {}

    def take(summary, source):
        sid = summary["id"]
        if sid in found and found[sid]["source"] == "transcript":
            return
        summary = dict(summary, source=source)
        found[sid] = summary

    # git notes (shared)
    notes = gitio.git(repo, "log", "--notes=" + NOTES_REF, "--format=%x1e%N", "%s..%s" % (base_sha, head_sha), check=False)
    for rec in notes.split("\x1e"):
        for line in rec.strip().splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            s = (data.get("by_branch") or {}).get(branch)
            if s and (branch != "HEAD" or data.get("session_id") in trailer_ids):
                take(dict(s, id=data.get("session_id", s.get("id"))), "git-notes")

    # local summaries written by the SessionEnd hook
    folder = summaries_dir(repo)
    if os.path.isdir(folder):
        for path in glob.glob(os.path.join(folder, "*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            by_branch = data.get("by_branch") or {}
            s = by_branch.get(branch)
            if s is None and data.get("session_id") in trailer_ids and by_branch:
                s = max(by_branch.values(), key=lambda x: x.get("tool_calls", 0))
            if s:
                take(dict(s, id=data.get("session_id", s.get("id"))), "summary")

    # raw transcripts (freshest and most detailed when still on disk)
    needle = ('"gitBranch":"%s"' % branch).encode("utf-8")
    for path in _transcript_files(repo, scan_all):
        sid = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        if needle not in blob and sid not in trailer_ids:
            continue
        by_branch = summarize_transcript(path)
        s = by_branch.get(branch)
        if s is None and sid in trailer_ids and by_branch:
            s = max(by_branch.values(), key=lambda x: x.get("tool_calls", 0))
        if s:
            found.pop(s["id"], None)
            take(s, "transcript")

    sessions = sorted(found.values(), key=lambda s: s.get("start") or "")
    totals = collections.Counter()
    for s in sessions:
        totals["sessions"] += 1
        totals["tool_calls"] += s.get("tool_calls", 0)
        totals["human_messages"] += len(s.get("human_messages", []))
        totals["interrupts"] += s.get("interrupts", 0)
        totals["duration_s"] += s.get("duration_s") or 0
        for k, v in (s.get("tokens") or {}).items():
            totals[k] += v
    return {
        "branch": branch,
        "sessions": sessions,
        "trailers": trailers,
        "missing": sorted(trailer_ids - set(found)),
        "totals": dict(totals),
    }
