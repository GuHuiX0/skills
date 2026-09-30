# Production Delivery Checklist

## Before coding
- What user/business invariant is changing?
- What services, tables, events, APIs, and configs are in the path?
- Which components can be independently deployed?
- What versions can coexist during rollout?

## Before merge
- Failure modes considered?
- Data migration safe for existing data?
- New code compatible with old state/version?
- Observability sufficient to detect bad behavior?
- Tests cover the important invariant rather than only the happy path?

## Before deploy
- Preconditions known?
- Rollout order known?
- Stop conditions explicit?
- Rollback and data-recovery path understood?
- Expected metrics/logs/traces identified?

## After deploy
- Smoke test passed?
- Key invariants checked?
- Errors/latency/saturation healthy?
- Downstream consumers healthy?
- Any cleanup or follow-up migration required?

## After incident
- Trigger
- Impact
- Detection
- Root cause / contributing factors
- Mitigation
- Recovery
- Prevention
- What signal could have caught it earlier?
