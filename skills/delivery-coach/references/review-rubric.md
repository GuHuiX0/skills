# Delivery Review Rubric

Score is intentionally qualitative; do not optimize for a numeric grade.

## System model
Can the engineer name the relevant entry point, services, tables, contracts, and dependencies?

## Invariants
Can they state what must remain true?

## Change impact
Can they predict which consumers, data, versions, and operational signals change?

## Failure reasoning
Can they reason through timeout, retry, duplicate, partial failure, and crash cases?

## Compatibility
Can old and new versions coexist safely?

## Verification
Can they distinguish test evidence from runtime evidence?

## Recovery
Can they explain rollback, forward-fix, and data recovery?

## Ownership
Can they communicate what changed, what was verified, what remains uncertain, and what follow-up is needed?
