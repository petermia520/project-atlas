"""What differs between the coding agents Project Atlas supports.

    claude-code   ~/.claude/projects/<encoded cwd>/<id>.jsonl      records gitBranch per entry
    pi            ~/.pi/agent/sessions/--<cwd>--/<ts>_<id>.jsonl    no branch; the extension adds
    omp           ~/.omp/agent/sessions/<encoded cwd>/<ts>_<id>.jsonl   `project-atlas.branch` entries
"""

import glob
import json
import os

AGENTS = ("claude-code", "pi", "omp")
BRANCH_ENTRY = "project-atlas.branch"
UNKNOWN_BRANCH = "(unknown)"


def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def session_roots():
    """[(agent, sessions_dir)] for pi and omp, from env overrides and default locations."""
    home = os.path.expanduser("~")
    roots = []
    for var in ("ATLAS_PI_SESSIONS",):
        if os.environ.get(var):
            roots.append(("pi", os.environ[var]))
    for var in ("PI_AGENT_DIR", "PI_CODING_AGENT_DIR"):
        if os.environ.get(var):
            roots.append(("pi", os.path.join(os.environ[var], "sessions")))
    roots.append(("pi", os.path.join(home, ".pi", "agent", "sessions")))
    if os.environ.get("ATLAS_OMP_SESSIONS"):
        roots.append(("omp", os.environ["ATLAS_OMP_SESSIONS"]))
    if os.environ.get("PI_CODING_AGENT_SESSION_DIR"):
        roots.append(("omp", os.environ["PI_CODING_AGENT_SESSION_DIR"]))
    config = os.environ.get("PI_CONFIG_DIR") or ".omp"
    base = os.path.join(home, config)
    roots.append(("omp", os.path.join(base, "agent", "sessions")))
    roots.extend(("omp", p) for p in glob.glob(os.path.join(base, "profiles", "*", "agent", "sessions")))
    seen, out = set(), []
    for agent, path in roots:
        real = os.path.realpath(path)
        if real not in seen and os.path.isdir(real):
            seen.add(real)
            out.append((agent, real))
    return out


def read_header(path):
    """The first JSON object of a transcript, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    return json.loads(line)
    except (OSError, ValueError):
        return None
    return None


def transcript_format(path):
    """"pi" for pi/omp session files (header line `{"type": "session", ...}`), else "claude"."""
    head = read_header(path) or {}
    return "pi" if head.get("type") == "session" and "version" in head else "claude"


def agent_for_path(path, default="pi"):
    real = os.path.realpath(path)
    if os.sep + ".omp" + os.sep in real or os.environ.get("PI_CONFIG_DIR", "\0") in real:
        return "omp"
    if os.sep + ".claude" + os.sep in real:
        return "claude-code"
    return default


def trailer_context(session_id, cli_path=None):
    """Instructions an agent gets at session start in repos that use Project Atlas."""
    text = (
        "This repository uses Project Atlas for branch reviews. When you create a git commit in this session, "
        "end the commit message with these trailers (after a blank line, before any Co-Authored-By line):\n"
        "Agent-Session: %s\n"
        "Agent-Decision: <one line per non-obvious choice and why, e.g. 'used X instead of Y because Z'> (optional, repeatable)\n"
        "Agent-Assumption: <one line per assumption the task did not settle> (optional, repeatable)\n"
        "Reviewers read these to understand the branch. Do not add trailers to commits you did not write."
        % (session_id or "<your session id>")
    )
    if cli_path:
        text += "\nProject Atlas CLI: python3 \"%s\"" % cli_path
    return text


AGENTS_MD_SNIPPET = """## Commit trailers (Project Atlas)

When you commit on a branch, end the commit message with trailers so reviewers can follow your work:

    Agent-Session: <your session id, if your tool shows one>
    Agent-Decision: <one line per non-obvious choice and why>
    Agent-Assumption: <one line per assumption the task did not settle>

Add Agent-Decision and Agent-Assumption only when there is something to say. Never add trailers to commits you did not write.
"""
