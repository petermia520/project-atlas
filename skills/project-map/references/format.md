# .project-map formats

## atlas.json

```json
{
  "schema": 1,
  "name": "payments-api",
  "language": "zh-CN",
  "main_ref": "main",
  "layers": [
    {"id": "entry",  "name": "入口"},
    {"id": "domain", "name": "业务域"},
    {"id": "infra",  "name": "基础设施"}
  ],
  "groups": [
    {"id": "webhooks", "name": "商户通知", "layer": "domain",
     "include": ["payments/webhooks/**"], "exclude": [],
     "about": "把支付事件推送到商户的回调地址，负责签名、投递和失败处理。"},
    {"id": "infra", "name": "infra/", "layer": "infra",
     "include": ["payments/infra/**", "payments/jobs/queue.py"]}
  ],
  "flows": [
    {"id": "order-notify", "name": "下单通知", "about": "订单状态变化 → 签名 → 推送到商户回调地址",
     "chains": [["payments/api/orders.py", "payments/webhooks/delivery.py", "payments/webhooks/signatures.py", "payments/infra/http.py"]]}
  ],
  "external": ["httpx", "redis"],
  "external_layer": "infra",
  "review": {"stale_threshold": 0.3},
  "scan": {
    "granularity": "auto",
    "max_file_modules": 150,
    "exclude": ["**/migrations/**"],
    "classify": {"test": ["e2e/**"]},
    "python_roots": ["src"],
    "coverage_files": ["coverage.xml"]
  }
}
```

- `groups[].include` / `exclude`: globs over module ids (`**`, `*`, `?`, `{a,b}`). The first group that matches a module wins.
- Module ids are repo-relative paths: a file (`payments/api/orders.py`), a directory when granularity is `dir` (`payments/api`), or a config file (`config/prod.yaml`).
- `flows[].chains`: each chain is drawn as one line through the modules in order. Use several chains for a flow that branches.
- `external`: package names as imported (`httpx`, `@scope/pkg`). They appear as modules named `ext:<name>`.
- `external_layer`: which layer the third-party group goes in (default: a final "Other" band).
- `scan` settings change what `facts` analyses. After changing them, run `facts` again.

## modules/<slug>.md

```markdown
---
module: payments/webhooks/delivery.py
rev: 4f2c1a9e0b7d6c5a4f3e2d1c0b9a8f7e6d5c4b3a
hash: 3b1f0a9c2e7d4f61
refs: delivery.py:12-74
---
把支付事件 POST 到商户的回调地址，负责签名头和失败处理。所有商户通知都经过这里；失败时抛出 WebhookError，由调用方决定是否重试。
```

- Get the file path from `atlas page-path <module id>` (add `--pending` for a rewrite that needs the owner's approval).
- `rev` = `map.json` top-level `rev`; `hash` = `map.json` `modules[<id>].hash`.
- `refs`: the line ranges you read, comma-separated.

## pins.md (people only)

```markdown
# Pins

## payments/utils/retry.py
- 所有对外重试统一走这个模块，方便统一限流和观测（ADR-014）。 — @platform, 2026-03-02

## payments/webhooks/**
- 签名算法变更要提前 30 天通知商户。 — @payments-core, 2025-11-03
```

- A `##` heading is a module id or a glob. Each `-` bullet is one note; `— @owner, YYYY-MM-DD` is optional.
- The map shows pins on every matching module, and branch reports check changes against them.
