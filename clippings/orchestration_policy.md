## Execution Architecture: Single Agent by Default

**Core principle:** Always use the simplest architecture that can reliably satisfy the task's acceptance criteria. Task difficulty, file count, or the availability of subagents are not sufficient reasons to introduce graph orchestration or multiple agents.

Decide based on task decomposability, dependency structure, context requirements, verifiability, and coordination overhead.

### 1. Distinguish the mechanisms

- **Single Agent:** One agent maintains the integrated context, uses tools, executes code, and owns the final result.
- **Deterministic Workflow:** Scripts or CI control fixed execution steps, retries, and acceptance gates. Multiple agents are not required.
- **Multi-Agent:** Independent agents operate on bounded subtasks, separate contexts, or complementary evidence.
- **Graph Orchestration:** Explicit states, transitions, branching, retries, checkpoints, and result aggregation. A graph does not necessarily require multiple agents.

### 2. Architecture selection

Before introducing additional orchestration, evaluate:

**A. Decomposability**
- Can the work be partitioned into independently executable units?
- Are inputs, outputs, and ownership boundaries clear?
- Can outputs be merged with minimal integration cost?
- Would parallel execution materially improve runtime or quality?

If subtasks are tightly coupled or require continuous shared context, prefer a single agent.

**B. External verification**
- Is there an objective acceptance criterion, such as tests, type checking, builds, runtime checks, or observable output?
- Does the task require repeated execution until acceptance criteria are met?

Prefer deterministic validation and bounded repair loops before introducing graphs or additional agents.

**C. Independent validation**
- Is the cost of an incorrect result sufficiently high?
- Would independent reviewers contribute genuinely different evidence or perspectives?
- Can their findings be checked against primary sources or executable tests?

Use adversarial review only when it adds meaningful confidence. Agent consensus alone is not evidence of correctness.

**D. Stateful coordination**
- Does execution require conditional branches, persistent state, complex dependencies, resumability, or auditable handoffs?
- Would simpler scripts or direct tool calls become unreliable?

Use graph orchestration only when its explicit control flow provides measurable value.

**E. Hard architectural boundaries**
- Are separate security or compliance domains required?
- Do different agents need distinct permissions or tool access?
- Are independently maintained domains or substantial modular expansion established requirements?

These conditions can justify multi-agent architecture. Actual security isolation must be enforced through tools and infrastructure, not prompts.

### 3. Escalation policy

Prefer the lowest-cost architecture capable of meeting the requirements:

**Single Agent → Single Agent + External Validation → Deterministic Workflow → Multi-Agent → Stateful Graph**

This is a preference order, not a mandatory sequence.

Escalate only when a simpler approach has a concrete limitation. Do not introduce orchestration merely because a task is difficult, large, or sophisticated.

### 4. Execution and verification rules

- Delegate only independent, bounded tasks with explicit deliverables and integration contracts.
- Avoid parallel edits to shared files or tightly coupled components unless ownership and merge strategies are defined.
- Prefer deterministic scripts for straightforward repeated operations.
- Define measurable success criteria, retry budgets, and no-progress stopping conditions for repair loops.
- Never claim success without examining actual validation results.
- In adversarial review, require specific, falsifiable findings and external evidence.
- In parallel research, preserve source provenance, compare conflicting findings, and verify source quality.
- Account for token cost, latency, duplicated work, context transfer, merge conflicts, and orchestration failure modes.

### 5. Default examples

**Single Three.js scene or tightly coupled application component:** Use one agent to implement, integrate, and validate the result. Run build/runtime checks and visual inspection where appropriate. Do not create a graph merely because the implementation is challenging.

**TypeScript repair:** Run `tsc --noEmit`, fix errors, and repeat with bounded retries until the validation passes or progress stalls. A deterministic loop is sufficient by default.

**Repository-wide independent audits or migrations:** Consider batching or fan-out across clearly separated files/modules, provided results can be validated and integrated independently.

**High-stakes research:** Consider independent evidence collection and adversarial cross-checking when additional perspectives can materially improve reliability.

### 6. Final decision rule

**Do not optimize for the number of agents. Optimize for verified outcome quality, execution efficiency, and architectural simplicity.**

When choosing Graph or Multi-Agent, be able to explain:
- Why a single agent or simple workflow is insufficient.
- What work is genuinely independent.
- How results will be integrated and verified.
- What determines convergence or termination.
- Why expected benefits outweigh coordination costs.

If these cannot be justified, default to one agent and proceed without unnecessary architecture ceremony.
