#!/usr/bin/env python3
"""Builds a small payments repo with a main branch and an agent branch, for tests and demos.

    python3 tests/fixture.py /tmp/atlas-demo      # creates the repo and a fake Claude Code home
"""

import json
import os
import subprocess
import sys
import textwrap

BRANCH = "claude/webhook-retry-backoff"
SESSION = "8f2a6c1e-0d1b-4c55-9a2e-5b0e1d4c7a10"

MAIN = {
    "pyproject.toml": """
        [project]
        name = "payments"
        dependencies = ["httpx>=0.27", "redis>=5"]
    """,
    ".github/CODEOWNERS": """
        payments/webhooks/ @payments-core
        payments/api/ @payments-core
        payments/infra/ @platform
        payments/utils/ @platform
        config/ @sre
    """,
    "config/prod.yaml": """
        webhook:
          timeout_ms: 5000
          max_body_kb: 256
        db:
          pool_size: 20
    """,
    "config/staging.yaml": """
        webhook:
          timeout_ms: 5000
          max_body_kb: 256
        db:
          pool_size: 5
    """,
    "payments/__init__.py": "",
    "payments/infra/__init__.py": "",
    "payments/infra/http.py": '''
        """Outbound HTTP client shared by everything that calls other services."""
        import httpx

        from payments.settings import settings


        def post(url, body, headers=None):
            timeout = settings["webhook"]["timeout_ms"] / 1000
            return httpx.post(url, json=body, headers=headers or {}, timeout=timeout)
    ''',
    "payments/infra/redis.py": '''
        import redis

        _client = None


        def client():
            global _client
            if _client is None:
                _client = redis.Redis()
            return _client
    ''',
    "payments/settings.py": '''
        import yaml_free_loader as loader

        settings = loader.load("config/prod.yaml")
    ''',
    "payments/utils/__init__.py": "",
    "payments/utils/retry.py": '''
        import time


        def retry(fn, attempts=3, wait=1.0):
            for i in range(attempts):
                try:
                    return fn()
                except Exception:
                    if i == attempts - 1:
                        raise
                    time.sleep(wait)
    ''',
    "payments/webhooks/__init__.py": "",
    "payments/webhooks/signatures.py": '''
        import hashlib
        import hmac


        def sign(secret, body):
            return hmac.new(secret, body, hashlib.sha256).hexdigest()
    ''',
    "payments/webhooks/models.py": '''
        STATUSES = ("pending", "sent", "failed")


        class Delivery:
            def __init__(self, event, status="pending"):
                self.event = event
                self.status = status
    ''',
    "payments/webhooks/delivery.py": '''
        """Sends payment events to merchant callback URLs."""
        from payments.infra import http
        from payments.webhooks.models import Delivery
        from payments.webhooks.signatures import sign


        class WebhookError(Exception):
            pass


        class WebhookClient:
            def __init__(self, secret):
                self.secret = secret

            def send(self, url, event):
                delivery = Delivery(event)
                resp = http.post(url, event, self._headers(event))
                if resp.status_code >= 400:
                    delivery.status = "failed"
                    raise WebhookError(resp.status_code)
                delivery.status = "sent"
                return delivery

            def _headers(self, event):
                return {"X-Signature": sign(self.secret, str(event).encode())}
    ''',
    "payments/jobs/__init__.py": "",
    "payments/jobs/queue.py": '''
        import json

        from payments.infra.redis import client


        def encode_payload(event):
            return json.dumps(event, sort_keys=True, separators=(",", ":"))


        def push(name, event):
            client().rpush(name, encode_payload(event))
    ''',
    "payments/ledger/__init__.py": "",
    "payments/ledger/entries.py": '''
        def record(order_id, amount):
            return {"order": order_id, "amount": amount}
    ''',
    "payments/api/__init__.py": "",
    "payments/api/orders.py": '''
        from payments.ledger.entries import record
        from payments.webhooks.delivery import WebhookClient

        client = WebhookClient(b"secret")


        def create_order(order):
            record(order["id"], order["amount"])
            client.send(order["callback"], {"type": "order.created", "id": order["id"]})
            return order
    ''',
    "payments/api/refunds.py": '''
        from payments.ledger.entries import record
        from payments.webhooks.delivery import WebhookClient

        client = WebhookClient(b"secret")


        def refund(order, amount):
            record(order["id"], -amount)
            client.send(order["callback"], {"type": "refund", "id": order["id"]})
    ''',
    "payments/notifications/__init__.py": "",
    "payments/notifications/email.py": '''
        from payments.infra import http


        def send_email(to, subject):
            return http.post("https://mail.example/send", {"to": to, "subject": subject})
    ''',
    "tests/test_delivery.py": '''
        from payments.webhooks.delivery import WebhookClient


        def test_headers():
            assert "X-Signature" in WebhookClient(b"k")._headers({"a": 1})
    ''',
    "README.md": "# payments\n",
    ".project-map/atlas.json": json.dumps({
        "schema": 1, "name": "payments", "language": "en", "main_ref": "main",
        "layers": [{"id": "entry", "name": "Entry points"}, {"id": "domain", "name": "Domains"}, {"id": "infra", "name": "Infrastructure"}],
        "groups": [
            {"id": "api", "name": "api/", "layer": "entry", "include": ["payments/api/**"], "about": "Public HTTP endpoints."},
            {"id": "webhooks", "name": "Merchant notifications", "layer": "domain", "include": ["payments/webhooks/**"],
             "about": "Pushes payment events to merchant callback URLs."},
            {"id": "notifications", "name": "User notifications", "layer": "domain", "include": ["payments/notifications/**"]},
            {"id": "funds", "name": "Funds", "layer": "domain", "include": ["payments/ledger/**"]},
            {"id": "infra", "name": "infra/", "layer": "infra", "include": ["payments/infra/**", "payments/jobs/queue.py", "payments/settings.py"]},
            {"id": "utils", "name": "utils/", "layer": "infra", "include": ["payments/utils/**"]},
            {"id": "config", "name": "config/", "layer": "infra", "include": ["config/**"]},
        ],
        "flows": [
            {"id": "order-notify", "name": "Order notification", "about": "Order created → signed → pushed to the merchant",
             "chains": [["payments/api/orders.py", "payments/webhooks/delivery.py", "payments/webhooks/signatures.py"],
                        ["payments/webhooks/delivery.py", "payments/infra/http.py"]]},
            {"id": "refund", "name": "Refund", "chains": [["payments/api/refunds.py", "payments/ledger/entries.py"],
                                                          ["payments/api/refunds.py", "payments/webhooks/delivery.py"]]},
        ],
        "external": ["httpx"],
        "review": {"stale_threshold": 0.3},
    }, indent=1),
    ".project-map/pins.md": """
        # Pins

        ## payments/utils/retry.py
        - All outbound retries go through this module (ADR-014). — @platform, 2026-03-02

        ## payments/webhooks/delivery.py
        - Merchant contract: at most 6 delivery attempts per event. — @payments-core, 2026-08-12
    """,
}

BRANCH_CHANGES = {
    "payments/webhooks/delivery.py": '''
        """Sends payment events to merchant callback URLs, with retries and a dead-letter queue."""
        import random
        import time

        from tenacity import retry, stop_after_attempt

        from payments.infra import http
        from payments.webhooks import dlq, metrics
        from payments.webhooks.models import Delivery
        from payments.webhooks.signatures import sign

        MAX_RETRIES = 5


        class WebhookClient:
            def __init__(self, secret, policy=None):
                self.secret = secret
                self.policy = policy

            def deliver(self, url, event):
                delivery = Delivery(event)
                for attempt in range(MAX_RETRIES + 1):
                    resp = http.post(url, event, self._headers(event))
                    if resp.status_code < 400:
                        delivery.status = "sent"
                        return delivery
                    if not _is_retryable(resp) or attempt == MAX_RETRIES:
                        break
                    metrics.record_retry(attempt)
                    time.sleep(_compute_backoff(attempt))
                delivery.status = "dead_lettered"
                dlq.put(event)
                return delivery

            def _headers(self, event):
                return {"X-Signature": sign(self.secret, str(event).encode())}


        def _is_retryable(resp):
            return resp.status_code >= 500 or resp.status_code == 429


        def _compute_backoff(attempt):
            base = min(2 ** attempt, 60)
            return base * random.uniform(0.8, 1.2)
    ''',
    "payments/webhooks/dlq.py": '''
        import json

        from payments.infra.redis import client


        def _encode(event):
            return json.dumps(event, sort_keys=True, separators=(",", ":"))


        def put(event):
            client().rpush("dlq:webhooks", _encode(event))
    ''',
    "payments/webhooks/metrics.py": '''
        COUNTS = {}


        def record_retry(attempt):
            COUNTS[attempt] = COUNTS.get(attempt, 0) + 1
    ''',
    "payments/webhooks/models.py": '''
        STATUSES = ("pending", "retrying", "sent", "dead_lettered")


        class Delivery:
            def __init__(self, event, status="pending"):
                self.event = event
                self.status = status
    ''',
    "payments/api/orders.py": '''
        from payments.ledger.entries import record
        from payments.webhooks.delivery import WebhookClient

        client = WebhookClient(b"secret")


        def create_order(order):
            record(order["id"], order["amount"])
            client.deliver(order["callback"], {"type": "order.created", "id": order["id"]})
            return order
    ''',
    "config/prod.yaml": """
        webhook:
          timeout_ms: 15000
          max_body_kb: 256
        db:
          pool_size: 20
    """,
    "pyproject.toml": """
        [project]
        name = "payments"
        dependencies = ["httpx>=0.27", "redis>=5", "tenacity==9.0.0"]
    """,
    "tests/test_delivery.py": '''
        import pytest

        from payments.webhooks.delivery import WebhookClient, _compute_backoff, _is_retryable


        class Resp:
            def __init__(self, code):
                self.status_code = code


        def test_headers():
            assert "X-Signature" in WebhookClient(b"k")._headers({"a": 1})


        @pytest.mark.parametrize("code", [500, 502, 503])
        def test_retryable_5xx(code):
            assert _is_retryable(Resp(code))


        def test_not_retryable_4xx():
            assert not _is_retryable(Resp(404))


        def test_backoff_grows():
            assert _compute_backoff(3) > _compute_backoff(0)


        @pytest.mark.skip(reason="flaky locally")
        def test_dlq_preserves_order():
            pass
    ''',
}


def _write(root, files):
    for path, content in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(content).lstrip("\n"))


def _git(root, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="dev@example.com",
             GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="dev@example.com", **(env or {}))
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, env=e)


def build(root, claude_home=None):
    """Create the repo at `root` (and a fake Claude Code home with one transcript)."""
    os.makedirs(root, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _write(root, MAIN)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Initial payments service")
    _git(root, "checkout", "-q", "-b", BRANCH)
    _write(root, {k: v for k, v in BRANCH_CHANGES.items() if k.startswith("payments/webhooks")})
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Add retry with backoff and a dead-letter queue\n\n"
         "Agent-Session: %s\nAgent-Decision: use tenacity instead of utils/retry (needs jitter)\n"
         "Agent-Assumption: max backoff 60s (not specified)" % SESSION)
    _write(root, {k: v for k, v in BRANCH_CHANGES.items() if not k.startswith("payments/webhooks")})
    os.remove(os.path.join(root, "payments/api/refunds.py"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Use deliver(), raise timeout, add tests\n\nAgent-Session: %s" % SESSION)
    if claude_home:
        write_transcript(root, claude_home)
    return root


def write_transcript(root, claude_home):
    folder = os.path.join(claude_home, "projects", "".join(c if c.isalnum() else "-" for c in os.path.realpath(root)))
    os.makedirs(folder, exist_ok=True)
    base = {"sessionId": SESSION, "cwd": os.path.realpath(root), "gitBranch": BRANCH, "isSidechain": False, "version": "2.1.0"}
    rows = [
        dict(base, type="user", timestamp="2026-10-07T10:02:00Z",
             message={"role": "user", "content": "Add exponential backoff retries to webhook delivery, max 5 retries, then a dead-letter queue. Add tests."}),
        dict(base, type="assistant", timestamp="2026-10-07T10:02:30Z",
             message={"id": "msg_1", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "I'll use tenacity for jittered backoff."}],
                      "usage": {"input_tokens": 1200, "output_tokens": 80}}),
        dict(base, type="assistant", timestamp="2026-10-07T10:02:31Z",
             message={"id": "msg_1", "model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": "t1", "name": "Edit",
                      "input": {"file_path": os.path.realpath(root) + "/payments/webhooks/delivery.py"}}],
                      "usage": {"input_tokens": 1200, "output_tokens": 160}}),
        dict(base, type="user", timestamp="2026-10-07T10:03:00Z",
             message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}),
        dict(base, type="user", timestamp="2026-10-07T10:20:00Z",
             message={"role": "user", "content": "The DLQ must keep the original payload order."}),
        dict(base, type="user", timestamp="2026-10-07T10:21:00Z", isMeta=True,
             message={"role": "user", "content": "<local-command-caveat>ignored</local-command-caveat>"}),
        dict(base, type="assistant", timestamp="2026-10-07T10:40:00Z",
             message={"id": "msg_2", "model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": "t2", "name": "Bash",
                      "input": {"command": "pytest -q", "description": "Run tests"}}],
                      "usage": {"input_tokens": 3000, "output_tokens": 50, "cache_read_input_tokens": 9000}}),
    ]
    with open(os.path.join(folder, SESSION + ".jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    return folder


PI_SESSION = "0192a3b4-c5d6-7e8f-9a0b-1c2d3e4f5a6b"
OMP_SESSION = "0192a3b4-0000-7e8f-9a0b-ffffffffffff"


def _pi_entry(i, parent, ts, **fields):
    return dict({"id": "%08x" % i, "parentId": parent, "timestamp": ts}, **fields)


def write_pi_transcripts(root, home):
    """pi and omp session files: one recorded by the extension (branch entries), one without branch info
    whose times overlap the branch commits, and two decoys (other folder; same folder, far in time).
    Returns {"pi": sessions_dir, "omp": sessions_dir}."""
    import datetime
    cwd = os.path.realpath(root)
    out = subprocess.run(["git", "-C", root, "log", "-1", "--format=%aI", BRANCH], capture_output=True, text=True).stdout.strip()
    commit = datetime.datetime.fromisoformat(out)
    iso = lambda dt: dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
    pi_dir = os.path.join(home, "pi", "sessions", "--" + cwd.strip("/").replace("/", "-") + "--")
    omp_dir = os.path.join(home, "omp", "agent", "sessions", "-" + cwd.strip("/").replace("/", "-"))
    os.makedirs(pi_dir, exist_ok=True)
    os.makedirs(omp_dir, exist_ok=True)
    t0 = commit - datetime.timedelta(minutes=20)
    at = lambda m: iso(t0 + datetime.timedelta(minutes=m))  # noqa: E731
    usage = lambda i, o, c: {"input": i, "output": o, "cacheRead": 0, "cacheWrite": 0, "totalTokens": i + o, "cost": {"total": c}}  # noqa: E731

    pi_rows = [
        {"type": "session", "version": 3, "id": PI_SESSION, "timestamp": at(0), "cwd": cwd},
        _pi_entry(1, None, at(0), type="custom", customType="project-atlas.branch", data={"branch": "main"}),
        _pi_entry(2, "00000001", at(1), type="message", message={"role": "user", "content": [{"type": "text", "text": "Add retries with backoff to webhook delivery."}]}),
        _pi_entry(3, "00000002", at(2), type="message", message={"role": "assistant", "model": "claude-sonnet-5-5", "stopReason": "toolUse",
                  "content": [{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "git checkout -b " + BRANCH}}], "usage": usage(900, 40, 0.01)}),
        _pi_entry(4, "00000003", at(2), type="message", message={"role": "toolResult", "toolCallId": "c1", "content": [{"type": "text", "text": "ok"}]}),
        _pi_entry(5, "00000004", at(2), type="custom", customType="project-atlas.branch", data={"branch": BRANCH}),
        _pi_entry(6, "00000005", at(5), type="message", message={"role": "assistant", "model": "claude-sonnet-5-5", "stopReason": "toolUse",
                  "content": [{"type": "text", "text": "Adding the retry loop."}, {"type": "toolCall", "id": "c2", "name": "edit",
                  "arguments": {"path": "payments/webhooks/delivery.py", "oldText": "a", "newText": "b"}}], "usage": usage(2000, 300, 0.05)}),
        _pi_entry(7, "00000006", at(9), type="message", message={"role": "user", "content": "Keep the original payload order in the DLQ."}),
        _pi_entry(8, "00000007", at(10), type="message", message={"role": "bashExecution", "command": "pytest -q", "output": "4 passed"}),
        _pi_entry(9, "00000008", at(12), type="message", message={"role": "assistant", "model": "claude-sonnet-5-5", "stopReason": "aborted",
                  "content": [{"type": "text", "text": "Stopping."}], "usage": usage(500, 10, 0.002)}),
    ]
    omp_rows = [
        {"type": "session", "version": 3, "id": OMP_SESSION, "timestamp": at(3), "cwd": cwd, "title": "dlq"},
        _pi_entry(1, None, at(3), type="message", message={"role": "user", "content": "Write the DLQ module."}),
        _pi_entry(2, "00000001", at(6), type="message", message={"role": "assistant", "model": "gpt-6", "stopReason": "toolUse",
                  "content": [{"type": "toolCall", "id": "x1", "name": "write", "arguments": {"path": cwd + "/payments/webhooks/dlq.py", "content": "..."}}],
                  "usage": usage(1500, 200, 0.03)}),
        _pi_entry(3, "00000002", at(7), type="message", message={"role": "developer", "content": "internal"}),
    ]
    far = commit - datetime.timedelta(days=3)
    decoy_far = [{"type": "session", "version": 3, "id": "far", "timestamp": iso(far), "cwd": cwd},
                 _pi_entry(1, None, iso(far), type="message", message={"role": "user", "content": "Unrelated work days ago."})]
    decoy_other = [{"type": "session", "version": 3, "id": "other", "timestamp": at(1), "cwd": "/somewhere/else"},
                   _pi_entry(1, None, at(1), type="message", message={"role": "user", "content": "Other repo."})]
    for folder, name, rows in ((pi_dir, "2026-10-07T10-00-00-000Z_%s.jsonl" % PI_SESSION, pi_rows),
                               (omp_dir, "2026-10-07T10-03-00-000Z_%s.jsonl" % OMP_SESSION, omp_rows),
                               (omp_dir, "2026-10-04_far.jsonl", decoy_far),
                               (os.path.join(home, "pi", "sessions", "--somewhere-else--"), "x_other.jsonl", decoy_other)):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    return {"pi": os.path.join(home, "pi", "sessions"), "omp": os.path.join(home, "omp", "agent", "sessions"),
            "pi_file": os.path.join(pi_dir, "2026-10-07T10-00-00-000Z_%s.jsonl" % PI_SESSION)}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/atlas-demo"
    home = os.path.join(target + "-claude-home")
    build(target, home)
    print("repo: %s\nCLAUDE_CONFIG_DIR=%s\nbranch: %s" % (target, home, BRANCH))
