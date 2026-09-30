# Failure Mode Matrix

Use this matrix to force concrete reasoning.

| Failure | Possible leftover state | Detection | Mitigation | Recovery |
|---|---|---|---|---|
| Timeout | Unknown whether side effect happened | Latency/error logs | Retry only if safe | Reconcile/idempotency |
| Duplicate request | Duplicate side effect | Duplicate-key/business metric | Idempotency | Deduplicate/reconcile |
| DB commit + event publish failure | Durable state without event | Outbox/consistency metric | Retry publish | Replay/reconcile |
| Mixed versions | Contract mismatch | Error rate / contract checks | Compatibility layer | Roll forward/back |
| Migration halfway | Partial schema/data state | Migration telemetry | Pause traffic/change | Resume/repair |
| Cache stale | Incorrect derived/read view | Cache hit + freshness signals | Invalidate/bypass | Rebuild |
| Downstream unavailable | Queue/backlog or failed requests | Dependency health | Backpressure/fallback | Replay/drain |
