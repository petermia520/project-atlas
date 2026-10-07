#!/usr/bin/env python3
"""Project Atlas command line. Run with no arguments for usage.

Map (main branch):     init · facts · summary · check · stale · page-path · approve · render map
Branch report:         report-dir · impact · sessions · transcript · ci · baseline · render report
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from atlas import __version__, ci, facts as factsmod, gitio, impact as impactmod, project, render, sessions as sessmod  # noqa: E402


def _root(args):
    return gitio.repo_root(args.repo)


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def _read_json(path, required=True):
    if not os.path.isfile(path):
        if required:
            raise project.AtlasError("missing %s" % path)
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _facts_path(root, given):
    return given or os.path.join(project.atlas_dir(root), "map.json")


def _load_facts(root, given):
    path = _facts_path(root, given)
    data = _read_json(path, required=False)
    if data is None:
        raise project.AtlasError("no facts at %s; run `facts` first" % path)
    return data


def report_dir(root, branch):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", branch or "detached").strip("-")
    return os.path.join(gitio.common_dir(root), "atlas", "reports", name)


# ---------------------------------------------------------------- map commands

def cmd_init(args):
    root = _root(args)
    folder = project.atlas_dir(root)
    os.makedirs(os.path.join(folder, "modules"), exist_ok=True)
    created = []
    atlas_path = os.path.join(folder, "atlas.json")
    if not os.path.exists(atlas_path):
        _write_json(atlas_path, {
            "schema": 1,
            "name": render.repo_name(root),
            "language": args.language,
            "main_ref": args.main or gitio.default_base(root).split("/")[-1],
            "layers": [],
            "groups": [],
            "flows": [],
            "external": [],
            "review": {"stale_threshold": 0.3},
            "scan": {"granularity": "auto", "exclude": []},
        })
        created.append(atlas_path)
    pins_path = os.path.join(folder, "pins.md")
    if not os.path.exists(pins_path):
        with open(pins_path, "w", encoding="utf-8") as fh:
            fh.write("# Pins\n\n<!-- Notes people pin to modules. The AI never edits this file.\n"
                     "## <module id or glob>\n- <the rule or fact> — @owner, YYYY-MM-DD -->\n")
        created.append(pins_path)
    print("\n".join(created) if created else "already initialised: " + folder)


def cmd_facts(args):
    root = _root(args)
    atlas = project.load_atlas(root) or {}
    rev = args.rev or gitio.default_base(root, atlas.get("main_ref"))
    data = factsmod.build_facts(root, rev, factsmod.scan_settings(atlas), with_coverage=args.coverage)
    out = _write_json(_facts_path(root, args.out), factsmod.strip_private(data))
    print("%s: %d modules, %d edges at %s (%s granularity)%s" % (
        out, len(data["modules"]), len(data["edges"]), gitio.short(data["rev"]), data["granularity"],
        ("; %d warnings" % len(data["warnings"])) if data["warnings"] else ""))


def cmd_summary(args):
    root = _root(args)
    print(factsmod.summary(_load_facts(root, args.facts), max_modules=args.max_modules))


def cmd_check(args):
    root = _root(args)
    result = project.check(root, _load_facts(root, args.facts))
    for e in result["errors"]:
        print("error: " + e)
    for w in result["warnings"]:
        print("warning: " + w)
    if not result["errors"] and not result["warnings"]:
        print("ok")
    return 1 if result["errors"] else 0


def cmd_stale(args):
    root = _root(args)
    facts = _load_facts(root, args.facts)
    atlas = project.load_atlas(root) or {}
    threshold = float((atlas.get("review") or {}).get("stale_threshold", 0.3))
    rows = project.stale(root, root, facts, threshold)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("all module pages are current")
    for r in rows:
        extra = (" (%.0f%% changed since %s)" % (r["ratio"] * 100, r.get("page_rev") or "?")) if r.get("ratio") is not None else ""
        print("%-8s %s%s" % (r["state"], r["module"], extra))
    return 0


def cmd_page_path(args):
    root = _root(args)
    print(project.page_path(root, args.module, pending=args.pending))


def cmd_approve(args):
    root = _root(args)
    print("approved: " + project.approve(root, args.module))


# ---------------------------------------------------------------- report commands

def _branch_and_dir(args, root):
    branch = args.branch or (gitio.current_branch(root) if args.head == "HEAD" else args.head)
    return branch, (args.dir or report_dir(root, branch))


def cmd_report_dir(args):
    root = _root(args)
    print(_branch_and_dir(args, root)[1])


def cmd_impact(args):
    root = _root(args)
    atlas = project.load_atlas(root) or {}
    branch, folder = _branch_and_dir(args, root)
    data = impactmod.compute(root, args.base, args.head, atlas=atlas, root=root, with_coverage=not args.no_coverage)
    if args.branch:
        data["branch"] = args.branch
    out = _write_json(args.out or os.path.join(folder, "impact.json"), data)
    mods = data["modules"]
    count = lambda s: sum(1 for m in mods.values() if m["status"] == s)  # noqa: E731
    src = data["lines"]["by_kind"].get("source", {})
    print("%s\n%s..%s · %d commits · %d files · source +%d -%d · modules: %d changed, %d new, %d deleted, %d affected · tests +%d" % (
        out, gitio.short(data["merge_base"]), gitio.short(data["head"]["sha"]), len(data["commits"]), len(data["files"]),
        src.get("added", 0), src.get("deleted", 0), count("changed"), count("new"), count("deleted"), count("affected"),
        data["tests"]["added"]))


def cmd_sessions(args):
    root = _root(args)
    branch, folder = _branch_and_dir(args, root)
    atlas = project.load_atlas(root) or {}
    base = gitio.resolve(root, args.base or gitio.default_base(root, atlas.get("main_ref")))
    head = gitio.resolve(root, args.head)
    mb = gitio.merge_base(root, base, head)
    data = sessmod.find(root, branch, mb, head, scan_all=args.all_projects)
    out = _write_json(args.out or os.path.join(folder, "sessions.json"), data)
    t = data["totals"]
    print("%s\n%d sessions · %d human messages · %d tool calls%s" % (
        out, t.get("sessions", 0), t.get("human_messages", 0), t.get("tool_calls", 0),
        (" · no data for trailer sessions: " + ", ".join(data["missing"])) if data["missing"] else ""))
    for s in data["sessions"]:
        print("- %s %s %s %s" % (s["id"], s.get("source"), s.get("start"), s.get("transcript_path") or ""))


def cmd_transcript(args):
    print(sessmod.condensed(args.path, max_len=args.max_len, include_tools=not args.no_tools))


def cmd_ci(args):
    root = _root(args)
    branch, folder = _branch_and_dir(args, root)
    data = ci.checks(root, branch)
    out = _write_json(args.out or os.path.join(folder, "checks.json"), data)
    print("%s\n%s" % (out, ("%d checks from %s" % (len(data["checks"]), data["source"])) if data["available"] else "unavailable: " + data["reason"]))


def cmd_baseline(args):
    root = _root(args)
    atlas = project.load_atlas(root) or {}
    branch, folder = _branch_and_dir(args, root)
    ref = args.ref or gitio.default_base(root, atlas.get("main_ref"))
    data = impactmod.baseline(root, ref, args.days, factsmod.scan_settings(atlas))
    out = _write_json(args.out or os.path.join(folder, "baseline.json"), data)
    print("%s\n%s" % (out, json.dumps(data)))


# ---------------------------------------------------------------- render

def cmd_render(args):
    root = _root(args)
    atlas = project.load_atlas(root) or {}
    pages, pins = project.load_pages(root), project.load_pins(root)
    if args.what == "map":
        facts = _load_facts(root, args.facts)
        model = render.build_map_page(root, facts, atlas, pages, pins)
        out = args.out or os.path.join(project.atlas_dir(root), "map.html")
    else:
        branch, folder = _branch_and_dir(args, root)
        impact = _read_json(os.path.join(folder, "impact.json"))
        sessions = _read_json(os.path.join(folder, "sessions.json"), required=False)
        report = _read_json(os.path.join(folder, "report.json"), required=False)
        checks = _read_json(os.path.join(folder, "checks.json"), required=False)
        baseline = _read_json(os.path.join(folder, "baseline.json"), required=False)
        if report:
            problems = validate_report(report)
            if problems:
                for p in problems:
                    print("report.json: " + p, file=sys.stderr)
                return 1
        model = render.build_report_page(root, impact, sessions, report, checks, atlas, pages, pins, baseline)
        out = args.out or os.path.join(folder, "report.html")
    render.write_html(model, out, args.title or render.default_title(model), fragment=args.fragment)
    print(out)
    return 0


SEVERITIES = {"crit", "warn", "info", "ok"}


def validate_report(r):
    """Human-readable problems with report.json (empty list when fine)."""
    problems = []
    if not isinstance(r, dict):
        return ["must be a JSON object"]
    v = r.get("verdict")
    if v is not None and (not isinstance(v, dict) or v.get("level") not in ("ready", "review", "block")):
        problems.append("verdict.level must be ready | review | block")
    for i, a in enumerate(r.get("attention") or []):
        if a.get("severity") not in SEVERITIES or not a.get("title"):
            problems.append("attention[%d] needs severity (crit|warn|info|ok) and title" % i)
    for i, s in enumerate(r.get("structure") or []):
        if s.get("severity") not in SEVERITIES or not s.get("title"):
            problems.append("structure[%d] needs severity and title" % i)
        for e in s.get("edges") or []:
            if not e.get("from") or not e.get("to"):
                problems.append("structure[%d].edges entries need from and to module ids" % i)
    scope = r.get("scope") or {}
    for key in ("requested", "extra", "missing"):
        if key in scope and not isinstance(scope[key], list):
            problems.append("scope.%s must be a list" % key)
    for item in scope.get("requested") or []:
        if item.get("status") not in ("done", "partial", "missing"):
            problems.append("scope.requested items need status done | partial | missing")
            break
    for i, c in enumerate(r.get("checks") or []):
        if c.get("status") not in ("pass", "fail", "warn", "pending", "skip"):
            problems.append("checks[%d].status must be pass | fail | warn | pending | skip" % i)
    return problems


# ---------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(prog="atlas", description="Project Atlas %s: project map and branch reports" % __version__)
    p.add_argument("--repo", default=".", help="path inside the git repository (default: .)")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="create .project-map/ with an empty atlas.json and pins.md")
    s.add_argument("--language", default="en", help="language for the pages, e.g. en or zh-CN")
    s.add_argument("--main", help="main branch name (default: detected)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("facts", help="scan a revision and write facts (default .project-map/map.json)")
    s.add_argument("--rev", help="revision to scan (default: main branch)")
    s.add_argument("--out")
    s.add_argument("--coverage", action="store_true", help="read coverage files from the working tree")
    s.set_defaults(fn=cmd_facts)

    s = sub.add_parser("summary", help="print a compact overview of the facts")
    s.add_argument("--facts")
    s.add_argument("--max-modules", type=int, default=250)
    s.set_defaults(fn=cmd_summary)

    s = sub.add_parser("check", help="validate .project-map against the facts")
    s.add_argument("--facts")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("stale", help="list module pages to write, rewrite, approve or delete")
    s.add_argument("--facts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_stale)

    s = sub.add_parser("page-path", help="print where a module's explanation page lives")
    s.add_argument("module")
    s.add_argument("--pending", action="store_true")
    s.set_defaults(fn=cmd_page_path)

    s = sub.add_parser("approve", help="replace a module page with its pending rewrite")
    s.add_argument("module")
    s.set_defaults(fn=cmd_approve)

    for name, fn, help_text in (
        ("report-dir", cmd_report_dir, "print the working folder for this branch's report"),
        ("impact", cmd_impact, "compare the branch with its base and write impact.json"),
        ("sessions", cmd_sessions, "collect the agent sessions behind the branch"),
        ("ci", cmd_ci, "collect CI check results with the gh CLI"),
        ("baseline", cmd_baseline, "test-to-source ratio of recent human changes"),
    ):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--base", help="base ref (default: main branch)")
        s.add_argument("--head", default="HEAD")
        s.add_argument("--branch", help="branch name (default: current branch)")
        s.add_argument("--dir", help="report working folder (default: inside .git/atlas/reports)")
        s.add_argument("--out")
        if name == "impact":
            s.add_argument("--no-coverage", action="store_true")
        if name == "sessions":
            s.add_argument("--all-projects", action="store_true", help="search every Claude Code project folder")
        if name == "baseline":
            s.add_argument("--ref")
            s.add_argument("--days", type=int, default=90)
        s.set_defaults(fn=fn)

    s = sub.add_parser("transcript", help="print a condensed, readable log of one session transcript")
    s.add_argument("path")
    s.add_argument("--max-len", type=int, default=300)
    s.add_argument("--no-tools", action="store_true")
    s.set_defaults(fn=cmd_transcript)

    s = sub.add_parser("render", help="render the map or the branch report to HTML")
    s.add_argument("what", choices=("map", "report"))
    s.add_argument("--facts")
    s.add_argument("--head", default="HEAD")
    s.add_argument("--branch")
    s.add_argument("--dir")
    s.add_argument("--out")
    s.add_argument("--title")
    s.add_argument("--fragment", action="store_true", help="omit <html>/<head>/<body> (for hosts that add them)")
    s.set_defaults(fn=cmd_render)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 0
    try:
        return args.fn(args) or 0
    except (gitio.GitError, project.AtlasError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
