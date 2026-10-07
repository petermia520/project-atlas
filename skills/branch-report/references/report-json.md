# report.json

The judgement layer of a branch report. Place it in the report folder (`atlas report-dir`) next to `impact.json`. Every top-level field is optional; the page leaves out sections with no data. `atlas render report` validates the file and prints what to fix.

```json
{
  "schema": 1,
  "language": "zh-CN",
  "task": "给 webhook 投递加指数退避重试，最多 5 次；失败后写入死信队列，并补测试。",

  "verdict": {
    "level": "review",
    "headline": "需人工确认 4 项",
    "summary": "任务完成，但失败时不再抛异常，且有一个测试被 skip。"
  },

  "attention": [
    {"severity": "crit", "tag": "行为", "title": "失败时不再抛异常",
     "detail": "deliver() 返回 DEAD_LETTERED；orders、reconcile 没检查返回值，会把失败当成功。",
     "where": "payments/webhooks/delivery.py:61"},
    {"severity": "warn", "tag": "测试", "title": "test_dlq_preserves_order 被 skip",
     "detail": "理由是本地 flaky，没有找到根因。", "where": "tests/test_dlq.py:88"}
  ],

  "scope": {
    "requested": [{"text": "指数退避重试，最多 5 次", "status": "done"},
                  {"text": "补测试", "status": "partial"}],
    "extra":     [{"text": "把 webhook.timeout_ms 从 5000 改成 15000"}],
    "missing":   [{"text": "docs/webhooks.md 未更新"}]
  },

  "structure": [
    {"severity": "warn", "tag": "重复实现", "title": "dlq._encode 复制了 queue.encode_payload",
     "detail": "约 80% 相同，可以直接引用。", "module": "payments/webhooks/dlq.py",
     "edges": [{"from": "payments/webhooks/dlq.py", "to": "payments/jobs/queue.py", "kind": "miss"}]}
  ],

  "pin_checks": [
    {"module": "payments/webhooks/delivery.py", "pin": "商户合同约定：同一事件最多投递 6 次。",
     "ok": true, "note": "1 次 + 5 次重试 = 6 次"}
  ],

  "tests": {
    "classification": [
      {"label": "有效", "severity": "ok", "count": 9, "advice": "保留", "detail": "测重试和死信的行为"},
      {"label": "重复", "severity": "warn", "count": 11, "advice": "合并成一个 parametrize"},
      {"label": "只测 mock", "severity": "warn", "count": 6, "advice": "改成断言结果，或删除"}
    ],
    "note": "清理后约 12 个测试，覆盖率不变。"
  },
  "mutation": {"killed": 9, "total": 31, "note": "删掉退避逻辑后，31 个新测试里 9 个失败"},

  "decisions": [
    {"title": "用 tenacity，不复用 utils/retry", "why": "需要抖动和异步。",
     "alternatives": ["扩展 utils/retry（约 60 行）"]}
  ],

  "review_order": ["payments/webhooks/delivery.py", "payments/webhooks/dlq.py", "config/prod.yaml"],
  "file_notes": {"config/prod.yaml": "超时 5000 → 15000（越界）"},
  "module_notes": {"payments/webhooks/delivery.py": ["失败路径返回值而不是抛异常。"]},

  "timeline": [
    {"session": "8f2a6c1e-...", "session_label": "会话 1 · 10:02–10:48", "text": "读代码，定位 send()", "kind": "step", "meta": ["只读"]},
    {"session": "8f2a6c1e-...", "text": "人：DLQ 要保留原始顺序", "kind": "human"},
    {"session": "8f2a6c1e-...", "text": "回滚并发写入方案", "kind": "revert", "meta": ["5b0e1d4"]}
  ],

  "checks": [
    {"name": "单元测试", "status": "warn", "summary": "434 通过 · 1 skip"}
  ]
}
```

## Fields

| Field | Values | Notes |
|---|---|---|
| `verdict.level` | `ready` · `review` · `block` | `review` = mergeable once a person checks the attention items |
| `attention[].severity`, `structure[].severity` | `crit` · `warn` · `info` · `ok` | sorted by you, most serious first |
| `attention[].id` | string | optional; keeps a reviewer's "checked" marks stable across re-renders |
| `scope.requested[].status` | `done` · `partial` · `missing` | |
| `structure[].module` | module id | makes the finding a link to that module on the map |
| `structure[].edges[]` | `{from, to, kind: "miss"}` | drawn as dashed "should reuse" arrows; both ends must be module ids |
| `pin_checks[]` | `{module, pin, ok, note}` | `pin` is the pin text (or its beginning) from `impact.json` `pins` |
| `tests.classification[].severity` | `crit` · `warn` · `info` · `ok` | colours the label |
| `timeline[].kind` | `step` · `human` · `revert` · `commit` · `interrupt` | when omitted, the page builds a timeline from sessions and commits |
| `checks[].status` | `pass` · `fail` · `warn` · `pending` · `skip` | when omitted, CI results from `atlas ci` are used |
