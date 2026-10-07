"""CI check results for a branch through the GitHub CLI (optional)."""

import json
import shutil
import subprocess

CONCLUSION = {
    "SUCCESS": "pass", "FAILURE": "fail", "TIMED_OUT": "fail", "CANCELLED": "fail", "ACTION_REQUIRED": "fail",
    "STARTUP_FAILURE": "fail", "ERROR": "fail", "NEUTRAL": "skip", "SKIPPED": "skip", "STALE": "skip",
    "PENDING": "pending", "EXPECTED": "pending",
}


def _gh(repo, *args):
    proc = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:300])
    return json.loads(proc.stdout or "null")


def checks(repo, branch):
    """{"available": bool, "source": str, "url": str|None, "checks": [{name, status, url, workflow}]}"""
    if not shutil.which("gh"):
        return {"available": False, "reason": "gh CLI is not installed", "checks": []}
    try:
        pr = _gh(repo, "pr", "view", branch, "--json", "number,url,statusCheckRollup")
        out = []
        for c in pr.get("statusCheckRollup") or []:
            name = c.get("name") or c.get("context") or "?"
            if c.get("__typename") == "StatusContext":
                status = CONCLUSION.get((c.get("state") or "").upper(), "pending")
                url = c.get("targetUrl")
            else:
                concl = (c.get("conclusion") or "").upper()
                status = CONCLUSION.get(concl, "pending") if concl else "pending"
                url = c.get("detailsUrl")
            out.append({"name": name, "status": status, "url": url, "workflow": c.get("workflowName")})
        return {"available": True, "source": "pull request #%s" % pr.get("number"), "url": pr.get("url"), "checks": out}
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        runs = _gh(repo, "run", "list", "--branch", branch, "--limit", "20",
                   "--json", "name,workflowName,status,conclusion,url,headSha")
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        msg = str(exc)
        if "auth login" in msg or "GH_TOKEN" in msg:
            msg = "gh CLI is not logged in"
        elif "no git remote" in msg.lower() or "none of the git remotes" in msg.lower():
            msg = "no GitHub remote"
        return {"available": False, "reason": msg.splitlines()[0][:120] if msg else "unavailable", "checks": []}
    latest = {}
    for r in runs or []:
        latest.setdefault(r.get("workflowName") or r.get("name"), r)
    out = []
    for name, r in latest.items():
        concl = (r.get("conclusion") or "").upper()
        out.append({"name": name, "status": CONCLUSION.get(concl, "pending") if concl else "pending",
                    "url": r.get("url"), "workflow": r.get("workflowName")})
    return {"available": True, "source": "workflow runs", "url": None, "checks": out}
