"""Agent sessions behind a branch, from Claude Code, pi and oh-my-pi (omp).

Sources, strongest first:
  1. commit trailers   `Agent-Session: <id>` (+ Agent-Decision / Agent-Assumption)   shared via git
  2. git notes         refs/notes/atlas-sessions (opt-in, written at session end)   shared once pushed
  3. local summaries   <git-common-dir>/atlas/sessions/<id>.json (session end)     this machine
  4. raw transcripts   Claude Code, pi and omp session files                       this machine, until cleanup

Claude Code records the git branch on every transcript entry. pi and omp do not; the Project
Atlas extension writes `project-atlas.branch` entries into their session files. Sessions with
no branch information are matched by working directory and commit times (matched_by "time").
"""

import collections
import datetime
import glob
import json
import os
import re

from . import agents, gitio

SKIP_PREFIXES = ("<local-command", "<command-name>", "<command-message>", "<command-args>", "<system-reminder>",
                 "<bash-input>", "<bash-stdout>", "<bash-stderr>", "Caveat:", "<skill", "[Skill")
EDIT_TOOLS = {"write", "edit", "multiedit", "multi_edit", "notebookedit", "notebook_edit", "apply_patch", "patch",
              "create_file", "str_replace", "hashline_edit"}
NOTES_REF = "atlas-sessions"
TIME_SLACK_BEFORE = datetime.timedelta(minutes=10)
TIME_SLACK_AFTER = datetime.timedelta(minutes=30)
claude_home = agents.claude_home


def encode_project_dir(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") in ("tool_result", "toolResult") for b in content):
            return None
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def _rel(path, cwd):
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return path


def _iso(ts):
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts / 1000.0, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return ts


def _parse(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds(a, b):
    fa, fb = _parse(a), _parse(b)
    return int((fb - fa).total_seconds()) if fa and fb else None


class _Bucket(dict):
    """One session's activity on one branch."""

    def __init__(self, session_id, branch, path, agent):
        super().__init__(id=session_id, agent=agent, branch=branch, source="transcript", transcript_path=path,
                         cwd=None, start=None, end=None, task=None, human_messages=[], interrupts=0, tool_calls=0,
                         tools=collections.Counter(), files_touched=set(), models=set(), subagent_tool_calls=0)
        self.usage = {}
        self.cost = 0.0

    def seen(self, ts):
        if ts:
            self["start"] = min(self["start"] or ts, ts)
            self["end"] = max(self["end"] or ts, ts)

    def human(self, text, ts, max_text, session):
        """session: dict shared by all buckets of one transcript; its first prompt is everyone's task."""
        text = text.strip()
        if not text or text.startswith(SKIP_PREFIXES):
            return
        if session.get("task") is None:
            session["task"] = text[:2000]
        else:
            self["human_messages"].append({"ts": ts, "text": text[:max_text] + ("…" if len(text) > max_text else "")})

    def tool(self, name, args, sidechain=False):
        self["tool_calls"] += 1
        self["tools"][name or "?"] += 1
        if sidechain:
            self["subagent_tool_calls"] += 1
        if (name or "").lower() in EDIT_TOOLS:
            args = args or {}
            fp = args.get("file_path") or args.get("path") or args.get("filePath") or args.get("notebook_path")
            if isinstance(fp, str):
                self["files_touched"].add(_rel(fp, self["cwd"]))

    def finish(self, session):
        self["task"] = session.get("task")
        tokens = collections.Counter()
        for usage in self.usage.values():
            for k, v in usage.items():
                if isinstance(v, int):
                    tokens[k] += v
        out = dict(self)
        out["tokens"] = dict(tokens)
        out["assistant_messages"] = len(self.usage)
        out["tools"] = dict(self["tools"].most_common())
        out["files_touched"] = sorted(self["files_touched"])
        out["models"] = sorted(self["models"])
        out["duration_s"] = _seconds(self["start"], self["end"])
        if self.cost:
            out["cost_usd"] = round(self.cost, 4)
        return out


def _summarize_claude(path, max_text):
    per, session = {}, {}
    session_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("type") not in ("user", "assistant"):
                continue
            branch = e.get("gitBranch") or "HEAD"
            session_id = e.get("sessionId") or session_id
            s = per.setdefault(branch, _Bucket(session_id, branch, path, "claude-code"))
            s["id"] = session_id
            s["cwd"] = s["cwd"] or e.get("cwd")
            ts = e.get("timestamp")
            s.seen(ts)
            msg = e.get("message") or {}
            if e["type"] == "assistant":
                if msg.get("id"):
                    s.usage[msg["id"]] = {k: (msg.get("usage") or {}).get(k) for k in
                                          ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
                if msg.get("model") and not msg["model"].startswith("<"):
                    s["models"].add(msg["model"])
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        s.tool(block.get("name"), block.get("input"), bool(e.get("isSidechain")))
                continue
            if e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
                continue
            text = _text_of(msg.get("content"))
            if not text:
                continue
            if text.strip().startswith("[Request interrupted by user"):
                s["interrupts"] += 1
                continue
            s.human(text, ts, max_text, session)
    return {b: s.finish(session) for b, s in per.items()}


def _summarize_pi(path, max_text, agent, initial_branch=None):
    per, session = {}, {}
    head = agents.read_header(path) or {}
    session_id = head.get("id") or os.path.splitext(os.path.basename(path))[0].split("_")[-1]
    cwd = head.get("cwd")
    branch = initial_branch or agents.UNKNOWN_BRANCH
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            kind = e.get("type")
            if kind == "custom" and e.get("customType") == agents.BRANCH_ENTRY:
                branch = (e.get("data") or {}).get("branch") or branch
                continue
            if kind != "message":
                continue
            msg = e.get("message") or {}
            role = msg.get("role")
            ts = _iso(e.get("timestamp") or msg.get("timestamp"))
            s = per.setdefault(branch, _Bucket(session_id, branch, path, agent))
            s["cwd"] = cwd
            if head.get("parentSession"):
                s["parent_session"] = head["parentSession"]
            s.seen(ts)
            if role == "assistant":
                usage = msg.get("usage") or {}
                s.usage[e.get("id") or str(len(s.usage))] = {
                    "input_tokens": usage.get("input"), "output_tokens": usage.get("output"),
                    "cache_read_input_tokens": usage.get("cacheRead"), "cache_creation_input_tokens": usage.get("cacheWrite")}
                cost = (usage.get("cost") or {}).get("total")
                if isinstance(cost, (int, float)):
                    s.cost += cost
                if msg.get("model"):
                    s["models"].add(msg["model"])
                if msg.get("stopReason") == "aborted":
                    s["interrupts"] += 1
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        s.tool(block.get("name"), block.get("arguments"))
            elif role == "user":
                text = _text_of(msg.get("content"))
                if text:
                    s.human(text, ts, max_text, session)
            elif role == "bashExecution" and msg.get("command"):
                s["human_messages"].append({"ts": ts, "text": "$ " + str(msg["command"])[:max_text]})
    return {b: s.finish(session) for b, s in per.items()}


def summarize_transcript(path, max_text=400, agent=None, initial_branch=None):
    """{branch: summary} for one transcript of any supported agent."""
    if agents.transcript_format(path) == "pi":
        return _summarize_pi(path, max_text, agent or agents.agent_for_path(path), initial_branch)
    return _summarize_claude(path, max_text)


def condensed(path, max_len=300, include_tools=True):
    """A readable log of one transcript: user text, agent text and tool calls (no thinking, no results)."""
    pi_format = agents.transcript_format(path) == "pi"
    lines = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            msg = e.get("message") or {}
            if pi_format:
                if e.get("type") == "custom" and e.get("customType") == agents.BRANCH_ENTRY:
                    lines.append("%s BRANCH: %s" % (str(e.get("timestamp", ""))[:19].replace("T", " "), (e.get("data") or {}).get("branch")))
                if e.get("type") != "message":
                    continue
                role, side = msg.get("role"), ""
                kind = {"user": "user", "assistant": "assistant"}.get(role)
                if role == "bashExecution":
                    lines.append("%s USER SHELL: %s" % (str(_iso(e.get("timestamp")))[:19].replace("T", " "), _clip(str(msg.get("command", "")), max_len)))
                    continue
                if not kind:
                    continue
            else:
                if e.get("type") not in ("user", "assistant") or e.get("isMeta"):
                    continue
                kind, side = e["type"], " [subagent]" if e.get("isSidechain") else ""
            ts = str(_iso(e.get("timestamp")) or "")[:19].replace("T", " ")
            if kind == "user":
                text = _text_of(msg.get("content"))
                if text and not text.strip().startswith(SKIP_PREFIXES):
                    lines.append("%s USER%s: %s" % (ts, side, _clip(text, max_len * 2)))
                continue
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    lines.append("%s AGENT%s: %s" % (ts, side, _clip(block["text"], max_len * 2)))
                elif include_tools and block.get("type") in ("tool_use", "toolCall"):
                    inp = block.get("input") or block.get("arguments") or {}
                    detail = inp.get("description") or inp.get("file_path") or inp.get("path") or inp.get("command") or inp.get("pattern") or ""
                    lines.append("%s TOOL %s%s: %s" % (ts, block.get("name"), side, _clip(str(detail), max_len)))
    return "\n".join(lines)


def _clip(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def summaries_dir(repo):
    return os.path.join(gitio.common_dir(repo), "atlas", "sessions")


def _claude_transcripts(repo, scan_all=False):
    home = os.path.join(claude_home(), "projects")
    if not os.path.isdir(home):
        return []
    dirs = set()
    if scan_all:
        dirs.update(glob.glob(os.path.join(home, "*")))
    else:
        for wt in gitio.worktrees(repo):
            for enc in {encode_project_dir(os.path.realpath(wt)), encode_project_dir(wt)}:
                dirs.update(glob.glob(os.path.join(home, glob.escape(enc) + "*")))
    files = []
    for d in sorted(dirs):
        files.extend(glob.glob(os.path.join(d, "*.jsonl")))
    return files


def _pi_transcripts():
    """[(agent, path)] for every pi / omp session file on this machine."""
    out = []
    for agent, root in agents.session_roots():
        for dirpath, _, names in os.walk(root):
            out.extend((agent, os.path.join(dirpath, n)) for n in names if n.endswith(".jsonl"))
    return out


def find(repo, branch, base_sha, head_sha, scan_all=False):
    log = gitio.git(repo, "log", "--format=%H%x1f%aI%x1f%(trailers:unfold,only)%x1e", "%s..%s" % (base_sha, head_sha))
    trailers, trailer_ids, commit_times = [], set(), []
    for rec in log.split("\x1e"):
        rec = rec.strip("\n")
        if rec.count("\x1f") < 2:
            continue
        sha, date, body = rec.split("\x1f", 2)
        t = _parse(date)
        if t:
            commit_times.append(t)
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = [x.strip() for x in line.split(":", 1)]
            if key.lower().startswith("agent-"):
                trailers.append({"sha": sha, "key": key, "value": value})
                if key.lower() == "agent-session":
                    trailer_ids.add(value)
    worktrees = [os.path.realpath(w) for w in gitio.worktrees(repo)]

    def in_repo(cwd):
        real = os.path.realpath(cwd) if cwd else ""
        return any(real == w or real.startswith(w + os.sep) for w in worktrees)

    def overlaps(s):
        a, b = _parse(s.get("start")), _parse(s.get("end"))
        return bool(a and b) and any(a - TIME_SLACK_BEFORE <= t <= b + TIME_SLACK_AFTER for t in commit_times)

    def pick(by_branch, sid):
        if by_branch.get(branch):
            return by_branch[branch], "branch"
        if sid in trailer_ids and by_branch:
            return max(by_branch.values(), key=lambda x: x.get("tool_calls", 0)), "trailer"
        unknown = by_branch.get(agents.UNKNOWN_BRANCH)
        if unknown and branch != agents.UNKNOWN_BRANCH and in_repo(unknown.get("cwd")) and overlaps(unknown):
            return unknown, "time"
        return None, None

    found = {}
    rank = {"transcript": 3, "summary": 2, "git-notes": 1}

    def take(summary, source, matched_by):
        sid = summary["id"]
        if sid in found and rank[found[sid]["source"]] >= rank[source]:
            return
        found[sid] = dict(summary, source=source, matched_by=matched_by)

    notes = gitio.git(repo, "log", "--notes=" + NOTES_REF, "--format=%x1e%N", "%s..%s" % (base_sha, head_sha), check=False)
    for rec in notes.split("\x1e"):
        for line in rec.strip().splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            s, how = pick(data.get("by_branch") or {}, data.get("session_id"))
            if s:
                take(dict(s, id=data.get("session_id", s.get("id"))), "git-notes", how)

    folder = summaries_dir(repo)
    for path in glob.glob(os.path.join(folder, "*.json")) if os.path.isdir(folder) else []:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        s, how = pick(data.get("by_branch") or {}, data.get("session_id"))
        if s:
            take(dict(s, id=data.get("session_id", s.get("id"))), "summary", how)

    needle = ('"gitBranch":"%s"' % branch).encode("utf-8")
    for path in _claude_transcripts(repo, scan_all):
        sid = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        if needle not in blob and sid not in trailer_ids:
            continue
        s, how = pick(summarize_transcript(path), sid)
        if s:
            take(s, "transcript", how)

    for agent, path in _pi_transcripts():
        head = agents.read_header(path) or {}
        if head.get("type") != "session":
            continue
        sid = head.get("id")
        if not in_repo(head.get("cwd")) and sid not in trailer_ids:
            continue
        s, how = pick(summarize_transcript(path, agent=agent), sid)
        if s:
            take(s, "transcript", how)

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
    cost = sum(s.get("cost_usd") or 0 for s in sessions)
    totals = dict(totals)
    if cost:
        totals["cost_usd"] = round(cost, 4)
    return {
        "branch": branch,
        "sessions": sessions,
        "trailers": trailers,
        "missing": sorted(trailer_ids - set(found)),
        "agents": sorted({s.get("agent", "claude-code") for s in sessions}),
        "totals": totals,
    }
