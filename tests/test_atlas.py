"""End-to-end tests on a generated repo. Run: python3 -m unittest discover -s tests -v"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

import fixture  # noqa: E402
from atlas import facts as factsmod, globs, impact as impactmod, langs, project, render, sessions  # noqa: E402

CLI = [sys.executable, os.path.join(ROOT, "scripts", "atlas_cli.py")]


class Repo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="atlas-test-")
        cls.repo = os.path.join(cls.tmp, "repo")
        cls.home = os.path.join(cls.tmp, "claude-home")
        fixture.build(cls.repo, cls.home)
        cls.env = dict(os.environ, CLAUDE_CONFIG_DIR=cls.home)
        cls.atlas = project.load_atlas(cls.repo)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def cli(self, *args, ok=True):
        proc = subprocess.run(CLI + list(args), cwd=self.repo, capture_output=True, text=True, env=self.env)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return proc


class TestUnits(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(globs.match("a/b/c.py", "a/**"))
        self.assertTrue(globs.match("a/b/c.py", "*.py"))
        self.assertTrue(globs.match("a/b/c.py", "a/{x,b}/*.py"))
        self.assertFalse(globs.match("a/b/c.py", "a/*.py"))
        self.assertTrue(globs.match("config/prod.yaml", "config/"))

    def test_yaml_keys(self):
        keys = langs.config_keys("c.yaml", "a:\n  b: 1  # note\n  c:\n    d: x\nlist:\n  - k: v\n")
        self.assertEqual(keys, {"a.b": "1", "a.c.d": "x"})

    def test_python_resolution(self):
        idx = langs.PythonIndex(["pkg/__init__.py", "pkg/a.py", "pkg/sub/b.py"], [""])
        a = langs.analyze_python("from . import a\nfrom .sub.b import f\nimport requests\nimport os\n")
        internal, external = idx.resolve("pkg/c.py", a)
        self.assertIn("pkg/a.py", internal)
        self.assertEqual(internal["pkg/sub/b.py"], {"f"})
        self.assertEqual(external, {"requests"})

    def test_line_classes(self):
        self.assertEqual(langs.classify_line("python", "  # hi"), "comment")
        self.assertEqual(langs.classify_line("python", "import os"), "import")
        self.assertEqual(langs.classify_line("python", "   "), "blank")
        self.assertEqual(langs.classify_line("python", "x = 1", 3, [[2, 4]]), "docstring")
        self.assertEqual(langs.classify_line("typescript", "// c"), "comment")

    def test_report_validation(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import atlas_cli
        self.assertEqual(atlas_cli.validate_report({"verdict": {"level": "ready"}}), [])
        self.assertTrue(atlas_cli.validate_report({"verdict": {"level": "maybe"}}))
        self.assertTrue(atlas_cli.validate_report({"attention": [{"severity": "high", "title": "x"}]}))


class TestFacts(Repo):
    def test_main_facts(self):
        f = factsmod.build_facts(self.repo, "main", factsmod.scan_settings(self.atlas))
        mods = f["modules"]
        self.assertEqual(f["granularity"], "file")
        self.assertNotIn("payments/__init__.py", mods, "empty __init__ files are not modules")
        self.assertIn("payments/webhooks/delivery.py", mods["payments/api/orders.py"]["imports"])
        self.assertEqual(mods["payments/api/orders.py"]["imports"]["payments/webhooks/delivery.py"], ["WebhookClient"])
        self.assertIn("webhook.timeout_ms", mods["payments/infra/http.py"]["config_reads"])
        self.assertIn("config/prod.yaml", mods["payments/infra/http.py"]["imports"])
        self.assertEqual(mods["payments/webhooks/delivery.py"]["owners"], ["@payments-core"])
        self.assertIn("httpx", f["external"])
        self.assertEqual(f["config_keys"]["webhook.timeout_ms"]["config/prod.yaml"], "5000")

    def test_check_and_stale(self):
        self.cli("facts", "--rev", "main")
        facts = project.load_facts(self.repo)
        result = project.check(self.repo, facts)
        self.assertEqual(result["errors"], [])
        mid = "payments/webhooks/delivery.py"
        page = project.page_path(self.repo, mid)
        os.makedirs(os.path.dirname(page), exist_ok=True)
        with open(page, "w") as fh:
            fh.write("---\nmodule: %s\nrev: %s\nhash: %s\nrefs: delivery.py:1-20\n---\nSends events.\n" % (mid, facts["rev"], facts["modules"][mid]["hash"]))
        states = {r["module"]: r["state"] for r in project.stale(self.repo, self.repo, facts)}
        self.assertNotIn(mid, states)
        self.assertEqual(states["payments/api/orders.py"], "missing")
        head = factsmod.build_facts(self.repo, fixture.BRANCH)
        states = {r["module"]: r for r in project.stale(self.repo, self.repo, head)}
        self.assertEqual(states[mid]["state"], "major")
        os.remove(page)


class TestImpact(Repo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = impactmod.compute(cls.repo, "main", "HEAD", atlas=cls.atlas, root=cls.repo)

    def test_statuses(self):
        m = self.data["modules"]
        self.assertEqual(m["payments/webhooks/delivery.py"]["status"], "changed")
        self.assertEqual(m["payments/webhooks/dlq.py"]["status"], "new")
        self.assertEqual(m["payments/api/refunds.py"]["status"], "deleted")
        self.assertEqual(m["payments/infra/http.py"]["status"], "affected")
        self.assertEqual(m["payments/infra/http.py"]["reasons"][0]["reason"], "reads-config")

    def test_symbols(self):
        syms = {(s["name"], s["change"]) for s in self.data["modules"]["payments/webhooks/delivery.py"]["symbols"]}
        self.assertIn(("WebhookClient.deliver", "renamed"), syms)
        self.assertIn(("WebhookClient.__init__", "signature"), syms)
        self.assertIn(("_compute_backoff", "added"), syms)
        self.assertNotIn(("WebhookClient", "modified"), syms)

    def test_edges_config_deps(self):
        self.assertIn(["payments/webhooks/dlq.py", "payments/infra/redis.py"], self.data["edges"]["added"])
        self.assertEqual(self.data["external"]["added"], ["tenacity"])
        self.assertEqual([(c["key"], c["old"], c["new"]) for c in self.data["config"]], [("webhook.timeout_ms", "5000", "15000")])

    def test_lines_and_tests(self):
        self.assertEqual(self.data["tests"]["added"], 4)
        self.assertEqual(len(self.data["tests"]["skipped_added"]), 1)
        self.assertGreater(self.data["lines"]["source_added"]["logic"], 0)
        self.assertIn("source", self.data["lines"]["by_kind"])

    def test_flows_pins_commits(self):
        self.assertEqual(self.data["flows"]["order-notify"], "direct")
        self.assertTrue(any(p["module"] == "payments/webhooks/delivery.py" for p in self.data["pins"]))
        keys = [t["key"] for c in self.data["commits"] for t in c["trailers"]]
        self.assertIn("Agent-Decision", keys)


class TestSessions(Repo):
    def test_transcript(self):
        sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
        os.environ["CLAUDE_CONFIG_DIR"] = self.home
        try:
            data = sessions.find(self.repo, fixture.BRANCH, sha, "HEAD")
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
        self.assertEqual(len(data["sessions"]), 1)
        s = data["sessions"][0]
        self.assertEqual(s["id"], fixture.SESSION)
        self.assertEqual(len(s["human_messages"]), 1, "tool results and meta messages are not human input")
        self.assertEqual(s["tokens"]["output_tokens"], 210, "usage is counted once per message id")
        self.assertEqual(s["files_touched"], ["payments/webhooks/delivery.py"])
        self.assertEqual(data["missing"], [])

    def test_session_end_hook(self):
        transcript = os.path.join(self.home, "projects")
        path = [os.path.join(dp, f) for dp, _, fs in os.walk(transcript) for f in fs if f.endswith(".jsonl")][0]
        payload = json.dumps({"session_id": fixture.SESSION, "transcript_path": path, "cwd": self.repo, "reason": "exit"})
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "session_end.py")], input=payload, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        saved = os.path.join(self.repo, ".git", "atlas", "sessions", fixture.SESSION + ".json")
        with open(saved) as fh:
            self.assertIn(fixture.BRANCH, json.load(fh)["by_branch"])

    def test_session_start_hook(self):
        payload = json.dumps({"session_id": "abc", "cwd": self.repo, "source": "startup"})
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "session_start.py")], input=payload, text=True, capture_output=True)
        out = json.loads(proc.stdout)
        self.assertIn("Agent-Session: abc", out["hookSpecificOutput"]["additionalContext"])
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "session_start.py")], input=json.dumps({"cwd": self.tmp}), text=True, capture_output=True)
        self.assertEqual(proc.stdout.strip(), "", "silent outside Atlas repos")


class TestRender(Repo):
    def test_cli_pipeline(self):
        self.cli("facts", "--rev", "main")
        self.cli("impact")
        self.cli("sessions")
        self.cli("baseline")
        folder = self.cli("report-dir").stdout.strip()
        with open(os.path.join(folder, "report.json"), "w") as fh:
            json.dump({"verdict": {"level": "review", "headline": "Check <b>2</b> things"},
                       "attention": [{"severity": "crit", "title": "<script>alert(1)</script>"}]}, fh)
        out = self.cli("render", "report").stdout.strip()
        with open(out) as fh:
            page = fh.read()
        self.assertNotIn("<script>alert(1)</script>", page, "data must be escaped in the JSON block")
        self.assertIn('id="atlas-data"', page)
        frag = self.cli("render", "report", "--fragment", "--out", os.path.join(self.tmp, "frag.html")).stdout.strip()
        with open(frag) as fh:
            self.assertFalse(fh.read().lstrip().startswith("<!doctype"))
        self.cli("render", "map")

    def test_bad_report_json(self):
        self.cli("impact")
        folder = self.cli("report-dir").stdout.strip()
        with open(os.path.join(folder, "report.json"), "w") as fh:
            json.dump({"verdict": {"level": "great"}}, fh)
        proc = self.cli("render", "report", ok=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("verdict.level", proc.stderr)
        os.remove(os.path.join(folder, "report.json"))

    def test_model_without_atlas(self):
        f = factsmod.build_facts(self.repo, "main")
        model = render.build_map_model(None, f, None, {}, [], "en")
        self.assertTrue(all(m["group"] for m in model["modules"].values()))


if __name__ == "__main__":
    unittest.main()
