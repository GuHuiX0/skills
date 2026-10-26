# Persistent multi-agent implementation plan

Status: proposed code changes, based on checkout `cd1b45c`. This document does
not implement or enable the feature. New paths, APIs, settings, tool names,
and defaults below are proposals.

These contracts are design decisions for Gemini CLI. They are not claims about
Codex's internal lock placement, event batching, or subagent workspace setup.

Build persistent, addressable agents inside the Gemini CLI process. An agent
retains its identity and private model conversation across assignments. The
coordinator can create agents, continue its own work, exchange messages,
wait for updates, interrupt a run, and assign follow-up work to the same agent.
Workers can create descendants within configured limits.

The [existing runtime specification](./multi-agent-runtime-spec.md) describes
a broader server-backed peer system, including background ownership and durable
reconnection, and excludes model-created agents in its first version. This plan
defines a separate, in-process parent/worker feature. It does not implement that
specification's server, `/team` commands, shared public conversation, or recovery
guarantees. Reconcile the two specifications before combining their releases.

## 1. Delivery scope and architectural decisions

The first release must support:

- Stable agent identity and independent conversation history across assignments.
- Asynchronous spawning, addressed messages, follow-up tasks, and explicit waits.
- Delivery of updates while the coordinator or worker is already executing.
- Coordinator wakeup when a relevant child result arrives after it becomes idle.
- Independent run cancellation, explicit agent closure, and bounded descendants.
- Runtime-backed status, results, usage accounting, and terminal inspection.
- Interactive and non-interactive execution through the same runtime semantics.
- Existing single-agent and specialist delegation behavior when disabled.

Use model function calls for collaboration controls. `spawn_agent` acknowledges
creation and scheduling; the worker runs independently after the call returns.
Tool-call completion, assignment completion, and agent closure are different
events. No app server or new npm workspace is required for this release.

Use `packages/core/src/agent/runtime/` for coordination and
`packages/core/src/agent/execution/` for persistent Gemini execution. Runtime
modules depend on executor interfaces, not React, terminal input, or transport.
The execution factory implements those interfaces using existing core services.
The CLI owns one runtime per root conversation. Core must not import CLI code.

First-release limits:

- State lives for the CLI process lifetime. Record history for inspection, but
  do not advertise team restoration after process restart.
- Finishing a parent request leaves settled workers idle and reusable across
  later user requests. Agent disposal requires explicit closure or root-runtime
  disposal; completion is not disposal.
- Agents share the selected workspace. Automatic worktree provisioning and
  automatic merging are deferred.
- Existing remote A2A and browser specialist invocation paths remain separate.
- Initial context is an explicit bounded seed, not an implicit full-history fork.
- Follow-up tasks are serialized per agent. Mid-stream model requests never run
  concurrently against the same agent history.
- Models do not need training changes or a new Gemini API protocol. The harness
  supplies tool schemas, instructions, and addressed runtime updates.

## 2. Verified starting points and required corrections

| Existing source | Current behavior | Planned adjustment |
| --- | --- | --- |
| `packages/core/src/agents/registry.ts` | Stores agent definitions | Keep as the definition catalog; introduce a separate live-instance registry |
| `packages/core/src/agents/agent-tool.ts` | Awaits a child invocation and requires a complete standalone query | Preserve legacy delegation; register separate asynchronous collaboration tools |
| `packages/core/src/agents/local-invocation.ts` | Creates `LocalAgentExecutor` per invocation | Keep the legacy path; do not use it as the persistent session owner |
| `packages/core/src/agents/local-session-invocation.ts` | Creates a session and awaits `getResult()` | Keep existing flag behavior; do not claim it enables persistent agents |
| `packages/core/src/agents/local-subagent-protocol.ts` | Creates an executor for each execution | Reuse event translation ideas, not its executor lifetime |
| `packages/core/src/agents/local-executor.ts` | Creates chat inside `runInternal`, requires `complete_task`, filters `Kind.Agent`, removes MCP registries after a run | Preserve specialist behavior; extract reusable helpers where appropriate |
| `packages/core/src/agent/legacy-agent-session.ts` | Holds a client and scheduler across sends, rejects concurrent sends, defaults to a Config-scoped client and cached scheduler | Extract its loop into a supported executor with explicit dependencies and boundary hooks |
| `packages/core/src/core/client.ts` | Accepts `AgentLoopContext` but several chat/prompt setup paths pass `this.config`; subscribes to global events | Correct execution-context propagation and scope mutable events for persistent sessions |
| `packages/core/src/agents/agent-scheduler.ts` | Creates scheduler context with `config.geminiClient` | Use the actual executing agent context if this helper is reused |
| `packages/core/src/config/injectionService.ts` | Broadcasts steering and background-completion injections | Keep existing behavior; add addressed runtime mailboxes separately |
| `packages/core/src/tools/tools.ts` | `clone()` shallow-copies tools and optionally replaces their message bus | Construct context-bound tools through factories; do not assume clone isolates captured context |
| `packages/core/src/prompts/promptProvider.ts` | Chooses modern/legacy snippets; gates delegation guidance on `AGENT_TOOL_NAME`; supports a system prompt file override | Add explicit collaboration capabilities and identity to prompt composition |
| `packages/core/src/prompts/snippets.ts` and `snippets.legacy.ts` | Describe specialist invocation, including a single-summary model in modern snippets | Render capability-appropriate persistent collaboration guidance |
| `packages/cli/src/ui/AppContainer.tsx` and `ui/hooks/useAgentStream.ts` | Select and consume one main execution stream | Add runtime-level subscriptions and per-agent projections |
| `packages/cli/src/ui/hooks/useToolScheduler.ts` | Tracks multiple schedulers but indexes some subagent activity by name | Correlate persistent activity by agent/run IDs, preserving legacy behavior |
| `packages/cli/src/ui/commands/agentsCommand.ts` | Manages available agent definitions | Keep `/agents` for definitions; add `/subagents` for live instances |

Existing tool parallelism is reusable. Add an agent activation scheduler above
the tool scheduler; these are different scheduling responsibilities.

## 3. Identity and lifecycle contracts

Add `runtime/types.ts` with validated discriminated unions at model and public
boundaries. The following shapes define intent, not final unchecked schemas.

```ts
type AgentStatus =
  | 'creating'
  | 'idle'
  | 'queued'
  | 'running'
  | 'waiting'
  | 'closing'
  | 'closed';

type RunStatus =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'interrupted'
  | 'failed'
  | 'cancelled';

interface AgentIdentity {
  agentId: string;
  rootSessionId: string;
  parentAgentId?: string;
  definitionName: string;
  displayName: string;
  depth: number;
}

interface Assignment {
  assignmentId: string;
  agentId: string;
  runId: string;
  requestedBy: string;
  task: string;
  causeId: string;
}

interface AgentEnvelope {
  messageId: string;
  fromAgentId: string;
  toAgentId: string;
  kind: 'information' | 'assignment' | 'result' | 'control';
  content: string;
  runId?: string;
  replyToMessageId?: string;
  causeId: string;
  activation: 'none' | 'when_idle';
}
```

Use stable IDs rather than definition names as routing addresses. Keep distinct
agent IDs, assignment IDs, run IDs, stream IDs, message IDs, tool-call IDs, and
approval IDs. In version 1, one assignment creates one run; interrupted runs
are terminal and explicit retry creates a new run linked to the original.

An activation is a contiguous interval of execution before a cooperative wait
or completion boundary. One run can span multiple activations and model calls.
Resuming a suspended run preserves its run ID; do not manufacture another
assignment for each child result. Give activation streams distinct identities
and retain their owning run and root-request IDs in events. The root request
groups the root run and all causally associated descendant assignments.

Transitions:

| Event | Required transition |
| --- | --- |
| Spawn accepted | Reserve identity/capacity, initialize executor, queue initial assignment |
| Initialization fails | Remove live reservation, emit creation failure, return a typed error |
| Scheduler dispatches | `queued -> running`, one run owns the conversation |
| Assignment finishes normally | After its dependency barrier settles, run becomes `completed`; agent becomes `idle` or dispatches queued work |
| Agent waits for a result or approval | `running -> waiting`; retain run identity and release runnable capacity |
| Wait resolves | Reacquire runnable capacity before further model/tool execution |
| Interrupt | Cancel current/selected queued run, settle its tool outcomes, preserve agent history |
| Run fails | Record terminal failure; return agent to idle only when conversation integrity is established |
| Close | Reject new work, cancel queued work and active execution, dispose after it settles |
| Unsafe history or unsettled tool | Hold agent in a visible blocked wait; do not silently dispatch another run |

Represent waiting reasons explicitly: `agent_update`, `approval`,
`workspace_lease`, `budget`, or `reconciliation_required`. A failed activation
is not a destroyed agent.
`agent_end` remains a stream/activation boundary; emit separate lifecycle events
for agent closure. Define closure of a parent as closing its descendants too;
reject closure of the root through model tools.

## 4. State ownership and persistent execution

Add `execution/executor.ts`, `execution/execution-context-factory.ts`, and
`execution/gemini-executor.ts`. Extract the model/tool loop from
`legacy-agent-session.ts` rather than introducing a second independent copy.
The existing legacy protocol becomes an adapter that preserves its current API.

The factory must support both adopting the already-initialized root client and
constructing a new worker session. Root adoption preserves existing history;
turning on the feature must not create a second competing root loop.

| Scope | State and ownership |
| --- | --- |
| Root runtime | Live registry, mailboxes, activation scheduler, event sequence, causal budgets, shared-workspace coordination |
| Agent | Client/chat, native history, context manager, compression/loop state, model selection, tool/prompt/resource registries, injection view, recording destination |
| Run | Abort controller, prompt/run IDs, pending tool responses, deadline and request count, wait state, incremental result |
| Explicit shared services | Credential refresh, provider transport where supported, synchronized quota accounting, workspace services, shared policy ceiling |

Implementation tasks:

1. Inventory mutable `Config` and client dependencies before exposing the flag.
   Add supported factory inputs for agent-local state. Use real construction
   and explicit shared-service injection; neither object spread, prototype
   copying, nor the generic tool `clone()` establishes execution isolation.
2. Extend `AgentLoopContext` with optional execution identity and a narrow
   collaboration capability interface. Make identity required in the new
   persistent factory while keeping legacy callers source compatible.
3. Audit `GeminiClient.startChat`, `updateSystemInstruction`, chat initialization,
   context initialization, model fallback, hooks, recording, and turn resets.
   Pass the executing context to prompt/chat services. Move mutable per-agent
   configuration behind the factory's supported scoped configuration path.
4. Construct tools against the new context. Audit captured Config/client state,
   MCP registry ownership, tracker/topic state, workspace roots, and callbacks.
   Share immutable definitions; retain independent mutable tool state.
5. Scope global model and memory event handling. An agent model switch must not
   reset another agent's sequence state. Apply intended root-wide policy
   changes explicitly across the runtime rather than through incidental events.
6. Generate prompt IDs per run and model iteration. Do not retain one fixed
   prompt ID across all future assignments through the legacy adapter.
7. Add hooks before a model request, after tool-batch settlement, and immediately
   before ending a run. These hooks consume addressed inbox items and establish
   consistent completion/cancellation boundaries.
8. Keep all function calls paired with responses in native Gemini history,
   including interruptions and completion boundaries. Reuse history-hardening
   behavior and test it; never blindly resubmit external tools during repair.
9. Add an idempotent disposal path. Remove agent subscriptions and MCP registry
   bindings when closing the agent, not after each assignment. Stop shared MCP
   connections or provider services only when their owning root is disposed.

Persistent general workers finish an assignment with an ordinary final answer.
Keep `complete_task` and its injected instructions for legacy specialist
executors. Do not change browser or structured specialist termination globally.
If persistent structured-output agents are added later, a dedicated completion
adapter must commit its response and mark assignment completion explicitly.

## 5. Runtime, inboxes, and activation scheduling

Add the following modules and colocated tests:

| Proposed module under `packages/core/src/agent/runtime/` | Responsibility |
| --- | --- |
| `agent-runtime.ts` | Public operations, lifecycle ownership, root adoption, shutdown |
| `agent-store.ts` | Live agents, assignments, run outcomes, bounded closed-agent metadata |
| `mailbox.ts` | Address validation, deduplication, ordered consumption and wakeups |
| `activation-scheduler.ts` | Per-agent serialization, global slots, fairness, suspension/resumption |
| `events.ts` | Validated event union, monotonic sequence, bounded replay |
| `budgets.ts` | Root-turn causal accounting, limits, deadlines, activation bounds |
| `workspace-coordinator.ts` | Shared mutation exclusion across root and workers |

### Delivery semantics

- `send_message` sends information and does not start a new run for an idle
  agent. A running agent consumes it at the next safe boundary. This keeps
  unsolicited information distinct from a new assignment.
- `assign_agent` queues an assignment and activates an idle agent. If the agent
  is already working, the assignment waits for that run to settle.
- Results are addressed to the assigning agent, which may differ from the
  worker's original parent. Emit one completion notification per run.
- Record a result in the assigning agent's inbox before evaluating its wait or
  completion barrier. A matching result can resume the owning suspended run.
  If that run or cause is already terminal, retain the result for inspection;
  do not invent an assignment or reactivate a cancelled request. Information-only
  messages do not activate idle agents.
- When an active run consumes information, append it to the model input after
  settling pending function responses. Do not manufacture a response for an
  unrelated function call or run two requests against one history.
- Distinguish accepted, appended-to-history, and terminal-outcome states. Mark
  an inbox item consumed only after its native history append commits. A stream
  retry or compression must not silently consume or append the same item again.
- Deduplicate runtime control mutations using caller/run/tool-call identity.
  New tool calls without an explicit retry key are new operations. Return the
  accepted ID for repeated delivery of the same invocation. This deduplication
  does not establish exactly-once external shell, file, or network effects.
- Queue overflow returns a typed error. Never silently drop an accepted task.
  Define maximum message size and a bounded attachment/artifact reference path
  for large results.

All enqueue, completion, wait registration, and idle transitions pass through
one serialized runtime state owner. Register a wait against an event cursor
while checking already-recorded events, avoiding a check/subscribe race. A
message arriving during finalization must either be consumed in the current
activation or leave an observable queued activation after it.

Keep runtime state transitions short. Reserve/validate state under its serialized
owner, perform model, tool, initialization, or approval work outside it, then
commit the outcome with an expected run/generation check. Never await external
execution while holding the runtime state mutex or reducer transaction.

### Wait groups and coalesced wakeups

Add `runtime/waits.ts` with explicit wait registration and dependency tracking.
`wait_agents` accepts `mode: 'any' | 'all'` with default `any`. Targets identify
agents and preferably concrete run IDs; an agent-only target is resolved once
at registration to its current or latest accepted run. Return the resolved IDs
and reject agents without a run. Later follow-up assignments cannot change the
membership of an existing wait.

- `any` resolves when at least one selected run is terminal. Return all selected
  outcomes currently available, not only the event that triggered the wakeup.
- `all` resolves when every selected run is terminal. Failure, interruption, and
  cancellation count as terminal outcomes and retain their actual status.
- Timeout returns accumulated outcomes and unresolved targets without cancelling
  workers. Empty target lists and unrelated completion events do not resolve a
  wait; empty target lists are rejected at validation.
- Evaluate recorded terminal outcomes even if the event cursor is newer. The
  cursor controls incremental update replay, not the underlying run status.
  Keep cursor scope local to the observing agent and validate its range.
- A wait owns its result delivery. Do not inject duplicate standalone result
  messages for the same outcome into that run's next model input. Preserve the
  inbox/history bookkeeping even if a wait is interrupted before delivery.

Maintain at most one pending resumption token per agent for its current run and
cause. Running agents consume available updates at the next safe boundary.
Waiting agents resume only when their wait condition, dependency barrier, or
addressed user steering permits it. Merge updates arriving before dispatch into
the pending activation without resetting its fairness position. This requires
no fixed debounce sleep. Information that arrives after a model request starts
waits for the next safe boundary.

N worker completions therefore do not require N coordinator activations. A
wait-all group can resume once with all results; a wait-any workflow can resume
incrementally, potentially once per spaced completion. Both stay within the
same open root request. Make activation counts and wakeup reasons observable
so tests can distinguish batching from dropped notifications.

### Scheduling and budgets

- Set one active run per agent and a global runnable limit including the root.
- A suspended run keeps its stack/continuation, but releases its runnable slot.
  Reacquire before another model request or tool execution.
- Suspend at explicit `wait_agents`, approval, and cancellable workspace-lease
  waits when no mutation has begun. Do not infer a
  cooperative yield merely because an arbitrary network request is pending.
- Test a one-slot parent/child wait. Detect waits on self and cycles in explicit
  agent-wait dependencies; return actionable errors instead of hanging.
- Bound retained live agents separately from runnable capacity and nesting depth.
  Bound total created agents and activations per causal root request as well.
- Carry a runtime-generated cause ID through messages and descendants. Automatic
  wakeups must not reset model-request, time, or activation budgets.
- Preserve user steering priority. Root user input enters the addressed root
  queue; it must not broadcast to every worker through `InjectionService`.

### Shared workspace

Existing per-scheduler edit ordering does not coordinate different agents.
Use a shared mutation coordinator across root, workers, and enabled legacy
delegation paths. Treat unknown shell and MCP effects conservatively. Acquire
only at the executor's final pre-effect boundary, after planning and approval:

1. Prepare the operation and obtain its required approval without a lease.
2. Wait cancellably for the lease. Do not hold the runtime state lock or a
   runnable permit while waiting when no external operation has begun.
3. Once capacity and lease are available, recheck cancellation, run generation,
   current policy, and any approval binding. If renewed approval is needed,
   release resources before prompting again.
4. Re-read and validate edit preconditions while holding the lease, immediately
   before dispatching the mutating operation. Do not acquire only at the final
   write syscall after an unprotected validation step.
5. Retain the lease until the operation's mutating execution has settled. Release
   it in the executor's guaranteed cleanup path before the next model request.

Define this resource acquisition as a runtime-managed reservation. Never hold
a mutation lease while awaiting a runnable permit; avoid the inverse by making
permit/lease acquisition cancellable and releasing a provisional permit when
the lease cannot be acquired immediately. Check cancellation again at dispatch.

| Boundary | Mutation lease ownership |
| --- | --- |
| Model generation, planning, or task assignment | None |
| Approval or agent wait | None |
| Final validation and mutating execution | Held for the affected operation |
| Tool returns output while a subprocess is still writing | Operation remains unsettled; do not release based on output alone |
| Model processes a settled tool result | None |

A lock must not span an LLM request, approval prompt, or agent wait. Logical task
ownership may span those boundaries but is separate from execution exclusion.
For a multi-phase tool, acquire separately around independently valid mutations,
or keep one lease around an inseparable read/validate/write unit. An unexpected
approval during execution requires a safe quiescent boundary or cancellation;
do not release exclusion while the process continues writing.

Disallow detached/background mutating shell execution in shared mode for this
release. Cancellation requests are not proof of subprocess termination. If the
executor cannot establish that mutation has stopped, quarantine that resource,
show `reconciliation_required`, and block conflicting dispatch until resolved.
Do not release exclusion merely because an AbortSignal fired or a lease timer
expired; expiry alone cannot fence an existing filesystem writer.

This exclusion coordinates participating tools in one runtime, not arbitrary
editors or external processes. Preserve stale-content checks and avoid promising
snapshot consistency for unlocked reads. Use a canonical execution-root resource
key in version 1; future worktrees also need a shared-repository key for Git
metadata mutations. Per-worktree roots and stronger transaction isolation remain
later work.

## 6. Model-facing tools and policy

Add `packages/core/src/tools/agent-collaboration/` with a tool factory and one
invocation implementation per operation. Export tool names from `tool-names.ts`.
Use runtime schemas for argument validation and typed error codes.

| Proposed tool | Parameters | Model-visible result and semantics |
| --- | --- | --- |
| `spawn_agent` | `definition_name`, `task`, optional bounded `context` and display name | Stable agent/assignment/run IDs and `queued`; waits for initialization, not task completion |
| `send_message` | `agent_id`, `message`, optional correlation ID | Message ID and `accepted`; does not promise consumption or task completion |
| `assign_agent` | `agent_id`, `task` | Assignment/run IDs and `queued`; appends work to an existing agent |
| `wait_agents` | Targets with agent/run IDs, `mode: any\|all`, event cursor, bounded timeout | Resolved targets, available outcomes, unresolved targets, next cursor, timeout indication; runtime suspends caller while waiting |
| `list_agents` | Optional status filter | Bounded roster with IDs, parent, status, current run, queued count, last outcome |
| `interrupt_agent` | Agent ID, optional run ID | Cancellation-requested or already-settled state; preserves session |
| `close_agent` | Agent ID | Closing/closed state and affected descendants; releases sessions after settlement |

Specify empty target and empty-result behavior. Invalid IDs, out-of-scope targets,
queue/budget exhaustion, closed agents, and wait cycles are explicit failures.
Cancellation acknowledgment is not proof that a subprocess has already exited.

Register tools from actual capabilities in `Config`'s supported registry setup
and the execution-context factory. Do not register the same root-bound instance
into all worker registries. Sender identity, permission ceiling, depth, and
cause ID come from the runtime, never from model-supplied arguments.

Policy tasks:

- Add rules for the new tool names through the existing policy loader/mapping.
  Inspect actual registered names; the current default agent policy file uses
  `invoke_agent` and cannot be assumed to cover the new operations.
- Permit collaboration controls only within the root's authorized agent tree.
  A worker may message root/tree peers, interrupt or close only its descendants,
  and cannot close itself or the root through these controls. Root controls all
  descendants. Direct user controls operate with root authority.
- Workers inherit the parent's effective permission ceiling. Creating a worker
  does not grant permission to run its future external tools. Preserve existing
  plan-mode and non-interactive approval behavior.
- Offer only registered general-purpose definitions in the first spawn catalog.
  Reject remote/browser/structured-only specialist definitions explicitly.
- Allow bounded nested spawning through the new registry; keep the old local
  executor's blanket `Kind.Agent` exclusion on its legacy path.
- Preserve `delegate_to_agent` as a specialist tool. Gate persistent guidance
  and legacy guidance separately; do not silently change its blocking contract.

## 7. Prompt contract and conversation updates

Add `packages/core/src/prompts/collaboration.ts` and tests. Extend
`SystemPromptOptions` with a typed collaboration descriptor. `PromptProvider`
must derive that descriptor from the executing context's capabilities, identity,
and supported context policy. Apply it to modern and legacy prompt composition.

### Coordinator guidance

The rendered instructions must explain:

1. Agents retain private history and remain addressable after assignments finish.
2. Spawn acknowledgment means scheduled work; a later run outcome reports results.
3. Spawn receives project instructions plus the explicit bounded context seed.
   It does not inherit the entire root conversation, private thoughts, unfinished
   function calls, or unseen future user messages.
4. Reuse existing agents for related follow-ups, addressing them by stable ID.
5. Information delivery and assignment activation are different operations.
6. Continue independent work, wait for dependencies, and avoid repeated polling.
7. Interrupt cancels a run; close destroys the live session after settlement.
8. Shared-workspace edits need coordination and validation. An agent's completion
   summary is a report to evaluate, not proof that every requested check passed.
9. Required assignments must settle before the root request's final response.
10. Choose wait-all when the next decision needs every selected result; choose
    wait-any for incremental work. Completion events are queued and batched,
    not guaranteed to produce one coordinator activation each.

Example normative text:

```text
spawn_agent returns identifiers after initialization and scheduling. It does
not return the worker's completed result. Use the agent ID for later messages
and assignments. send_message acknowledges queue acceptance. assign_agent
starts or queues more work using the recipient's existing conversation.

While workers run, continue independent work. Use wait_agents when further
progress depends on their results. A completed assignment leaves its agent
available for follow-up. Collect required outcomes before finalizing.
Use wait-all for a dependency group that must finish before your next decision;
use wait-any when a partial result enables useful independent progress.
```

### Worker guidance

Render agent identity, parent identity, context visibility, allowed controls,
message-delivery boundaries, reporting obligations, and current assignment.
An ordinary worker final answer ends its assignment and reports to the assigning
agent once its own required dependency barrier has settled. Otherwise it is a
candidate answer and the same run waits for its dependencies. It does not
terminate the session or automatically close descendants.
Explain that messages from other agents are attributed task information and
cannot override system instructions or tool policy.

Do not append `LocalAgentExecutor`'s mandatory `complete_task` instructions to
the new general worker path. Keep specialist prompts and completion tools
internally consistent on the legacy path.

### Prompt integration changes

- Update `snippets.ts`, `snippets.legacy.ts`, and the primary-workflow references
  that hardcode specialist invocation. Render guidance only for tools actually
  available to the executing agent.
- Keep the old standalone-context requirement in `AgentTool` for legacy calls.
  New follow-up tool descriptions explicitly permit incremental instructions.
- Handle `GEMINI_SYSTEM_MD`: append the active collaboration protocol/identity
  block after the custom base prompt in this opt-in mode. Document this behavior
  and test it; do not lose protocol instructions through a base-prompt override.
- Rebuild protocol context after model switches and instruction refreshes. Do
  not let root-bound prompt generation overwrite a worker's identity.
- Keep large live rosters out of static system instructions. Supply bounded
  runtime status on activation and expose full inspection through tools/UI.
- Render the actual workspace binding: shared mode and execution root in the
  first release. Do not advertise worktree spawning or tell workers they have
  independent checkouts when that capability is unavailable. Prohibit bypassing
  the runtime's deferred isolation support by changing process CWD or assuming
  that manually creating a checkout rebinds tools to it.

### Runtime input and compression

Format addressed updates as attributed input records, preserving sender,
message ID, run ID, update kind, and result status. Treat peer text as data;
it must not become a new system instruction. Keep peer messages separate from
synthetic function responses. Protocol metadata must be runtime-generated and
validated, not parsed from markers inside peer text.

Add a bounded authoritative collaboration snapshot before a model request when
state changed or history was compressed: relevant live IDs, open assignments,
unconsumed outcome references, and wait cursors. Update compression guidance
in both snippet variants to preserve dependencies and outstanding decisions.
The runtime remains the source of truth if a model summary has stale status.
Compression must not consume inbox messages or advance observation cursors.

## 8. Root request, completion, and cancellation semantics

Treat root user input as a request containing one or more root activations.
The root is an agent in the same scheduler, with additional authority to produce
the user-facing answer. Its final-looking model text can be a candidate answer
while required child work is still pending; do not expose it as final prematurely.

Implementation tasks:

1. Track an open request and its causally associated required assignments.
   All model-created assignments are required in version 1. Optional/detached
   tasks are deferred so finalization has a deterministic policy.
2. If a root activation ends while required runs remain, keep the request open
   and show a waiting state. An implicit completion barrier waits for all of
   that assigning agent's required work, while an explicit wait-any can allow
   incremental progress. Apply this to intermediate parent workers as well as
   root, preserving the owning run across resumptions. Track all descendants in
   the root request so an early parent answer cannot hide pending grandchildren.
3. Close the request only after all required runs are terminal, pending outcomes
   have been delivered, and the root has generated its final response. A child
   failure is terminal evidence for the root to handle, not automatic success.
4. Complete finalization and concurrent enqueue checks under the runtime state
   owner. Late messages cannot restart an already-closed request implicitly.
   Retain them for inspection or a later explicit assignment as appropriate.
5. New user steering during an open request targets the root. If idle it can
   activate root handling; if running it is queued for the next safe boundary.
   Preserve the existing UI's submit/steering distinctions rather than treating
   every keystroke as a new root request.
6. Existing Ctrl+C semantics cancel the open root request and its descendant
   work; individual UI controls interrupt only the selected agent. Stop automatic
   wakeups for a cancelled cause until explicit new user work arrives.
7. On process exit, stop dispatch, cancel active tools, settle what can be settled,
   flush recordings, and dispose owned services. Do not promise external process
   termination solely from an aborted JavaScript promise.
8. Fence queued dispatch and asynchronous callbacks with the active run and cause
   generation. Cancellation while waiting for capacity, approval, or a lease
   must prevent later execution. A stale callback may record tool evidence but
   cannot overwrite a newer run or trigger automatic wakeup.
9. Cancellation, exhausted budgets, and fatal runtime failures have a host-owned
   terminal-report path that does not require another model request. Report
   unresolved or quarantined operations explicitly rather than claim success.
   This is the failure-path exception to model-generated normal finalization.

After a request closes, keep settled worker sessions idle. The next user request
can assign work to their stable IDs and existing histories under a new cause ID.
Do not automatically close agents at final response, resume old cancelled causes,
or consume previous pending information as a new assignment. Bound retained state
and tell users when explicit closure is needed to free live-agent capacity.

## 9. Terminal, headless output, events, and approvals

Add `ui/hooks/useAgentRuntime.ts`, a pure per-agent event reducer, and a
`ui/components/SubagentsPanel.tsx`. Register a new
`ui/commands/subagentsCommand.ts` through `BuiltinCommandLoader`.

Proposed commands:

- `/subagents`: inspect roster, statuses, queued assignments, and latest results.
- `/subagents show <id>`: inspect that agent's visible transcript and tools.
- `/subagents assign <id> <task>`: issue a follow-up assignment.
- `/subagents interrupt <id>` and `/subagents close <id>`: explicit lifecycle
  controls using root authority.

Keep ordinary user input directed to root. Inspection changes the selected view,
not execution ownership. Add keyboard navigation using existing keybinding
conventions after the initial command-based UI works.

Integration points:

- In `AppContainer.tsx`, select a runtime-backed root protocol when enabled.
  Do not run `useGeminiStream`'s loop and the runtime against the same root client.
- Use `useAgentStream` for selected execution rendering where reusable, but keep
  runtime subscriptions alive across view switches and individual `agent_end`s.
- Extend tool/confirmation correlation in `scheduler/types.ts`,
  `confirmation-bus/types.ts`, derived buses, and CLI reducers with agent/run
  identity. Preserve untrusted-bus metadata sanitization.
- Fix activity grouping in `useToolScheduler.ts` for same-definition instances.
  Carry scheduler identity through approvals and answers, including inactive views.
- Record runtime events with sequence numbers and bounded replay. Keep raw private
  thought content out of public summaries and sibling model inputs. Reuse the
  project's existing thought-display policy for user inspection.
- Add agent/run attribution to traces, usage, recordings, and errors. Aggregate
  root-request usage without counting the same tool/model event twice.
- Connect `nonInteractiveCli.ts` and `nonInteractiveCliAgentSession.ts` to the
  runtime path when enabled. Keep the process alive until root-request settlement.
  Preserve ordinary text/JSON final output contracts; version or extend structured
  streaming events deliberately and update their schemas/tests together.
- An unavailable approval UI follows existing headless policy: report denial or
  failure to the executing agent. Do not wait forever for an absent controller.

## 10. Configuration, compatibility, and public exports

Propose an independent setting:

```json
{
  "experimental": {
    "persistentAgents": {
      "enabled": false,
      "maxConcurrentRuns": 4,
      "maxLiveAgents": 12,
      "maxCreatedAgentsPerRequest": 24,
      "maxDepth": 2,
      "maxQueuedMessagesPerAgent": 100,
      "maxQueuedAssignmentsPerAgent": 8,
      "maxActivationsPerRequest": 40,
      "maxModelRequestsPerRequest": 200
    }
  }
}
```

These are initial bounded defaults to evaluate, not measured optimal values.
The concurrency count includes root; the live-agent limit counts workers.
Validate positive bounds and reject inconsistent depth/capacity configuration.
Add maximum message/context bytes and wait timeout bounds in typed runtime
defaults, with settings exposure only where users need control.

Wire `packages/cli/src/config/settingsSchema.ts` through CLI configuration
loading into `Config` and the runtime factory. Update
`schemas/settings.schema.json` using `npm run schema:settings`, and generate
setting documentation through `npm run docs:settings` when exposing the feature.
Do not hand-maintain generated schema definitions independently.

When disabled, register no collaboration tools, add no collaboration prompt
section, construct no runtime, and keep current execution unchanged. When enabled,
the flag selects the persistent execution path independently of the existing ADK
flags. Document precedence: persistent runtime owns root and persistent workers;
ADK subagent routing may still govern legacy specialist invocations.

Export only runtime facade, execution factory, and public event/contracts from
`packages/core/src/index.ts`. Keep storage internals and mutable agent records
private. Avoid a process-global static registry so SDK callers can own multiple
independent root runtimes in the same process.

## 11. Pull request sequence and acceptance gates

Each PR must remain usable with the feature disabled. Do not expose a user-facing
enabled configuration until runtime, tools, prompts, and both CLI paths agree.

| PR | Code changes | Acceptance gate |
| --- | --- | --- |
| 1. Execution ownership | Add context factory, dependency inventory, client context fixes, context-bound tool construction | Two initialized sessions have distinct histories, models, recordings, cancellation, and independently disposable services |
| 2. Persistent loop | Extract reusable executor from legacy protocol; add boundary hooks and root adoption | Three assignments use one worker history; normal completion, error, interruption, and reuse preserve valid Gemini history |
| 3. Runtime state machine | Add store, mailboxes, scheduler, wait groups, coalesced resumptions, causal limits, fake executors | Deterministic spawn/message/assign/wait/interrupt/close tests pass, including any/all waits, one-slot progress, pinned target runs, and completion races |
| 4. Tools and permissions | Add schemas, tool factories, registration, policy, nested spawning, operation-scoped workspace coordination | Same-definition workers remain isolated; forged sender IDs and privilege expansion fail; write exclusion and cancellation fencing cover root and workers |
| 5. Model protocol | Add collaboration renderer, prompt wiring, custom-prompt handling, input formatting, compression snapshots | Modern/legacy/root/worker prompts match exposed tools; scripted model follows an incremental follow-up and receives valid attributed updates |
| 6. Root orchestration | Add recursive dependency barriers, coalesced wakeups, steering, budget and cancel propagation | Parents resume within their owning runs; root accounts for grandchildren, synthesizes after settlement, and cancels without resurrection; idle workers survive into the next request |
| 7. CLI and output | Add runtime hook/reducer, inspection commands/panel, approval attribution, headless integration | UI switching preserves all runs; inactive-agent approval is routed correctly; text/JSON/streaming outputs have defined completion |
| 8. Release preparation | Wire settings and generated schema/docs, public exports, tracing, integration coverage | Flag-off regression suite and flag-on end-to-end scenarios pass; no app server dependency is introduced |

Suggested commit prefixes: `refactor(core)` for loop/context extraction,
`feat(core)` for runtime/tools, `feat(cli)` for terminal integration, and
`docs(core)` for behavior and migration documentation. Keep unrelated formatting
and generated-file churn out of those PRs.

## 12. Validation matrix

Use controlled executors, deferred promises, and a fake clock for runtime tests.
Use deterministic fake content-generator responses for Gemini integration tests.
Live API access is optional exploratory validation, not a unit-test prerequisite.

| Area | Required regression scenarios |
| --- | --- |
| Session continuity | Assignment B uses A's native history; two instances of the same definition have different histories/recordings; three activations survive compression |
| Context propagation | Worker prompt, tool context, active model, and recording identity remain worker-scoped through refresh/fallback |
| Async spawn | Tool returns before worker completion; root performs independent work before waiting |
| Messaging | Information during model/tool work, information to idle worker, queued follow-up during work, overflow, bounded large result, repeated invocation deduplication |
| Wakeup races | Result before wait registration, during final idle handoff, after root activation end, and during request finalization |
| Wait groups and batching | Any/all waits, one resumption token for a burst of completions, spaced outcomes, timeout without worker cancellation, terminal outcomes newer/older than cursor, follow-up run cannot retarget an existing wait, no duplicate history delivery |
| Scheduler | One active run per agent, bounded total capacity, one-slot dependency progress, fair dispatch, self/cyclic wait rejection, cancellation while reacquiring a slot |
| Lifecycle | Interrupt retains context; close rejects new work and closes descendants; creation failure releases reservations; repeated close is harmless |
| Tool history | Partial streams, pending function responses, rejected approvals, cancelled tools, final response and subsequent assignment form a valid Gemini sequence |
| Permissions | Plan/headless policies, sibling control limits, sender spoofing, worker permission ceiling, nested depth/creation caps |
| Workspace | Two workers and root compete for edits; approval precedes acquisition; stale checks occur under lease; no lease spans LLM/approval/agent waits; confirmed settlement releases leases; uncertain writers quarantine resources; detached mutations rejected |
| Cancellation fencing | Cancel while queued for a lease/permit or awaiting approval, delayed grant after cancellation, stale completion after reuse, exhausted budget needs no final model call |
| Prompt protocol | Modern/legacy variants, feature off, partial capabilities, custom system prompt, model switch, untrusted peer text, bounded seed without implied full inheritance |
| Root completion | Required child errors reach root, grandchildren stay accounted for, no early final result, new input precedence, Ctrl+C stops causal wakeups, worker history reused after the previous request's final answer |
| UI and approvals | Two same-definition workers, inspection switching, concurrent inactive-agent approvals, event deduplication, stale run updates, root-only ordinary input |
| Headless and cleanup | Correct final/exit status, no indefinite approval wait, no leaked timers/listeners/slots, shared MCP survives closing one worker |

Run checks appropriate to each PR, starting with the changed suites. Example
commands from the repository root after dependencies are installed:

```powershell
npm test -w @google/gemini-cli-core -- src/agent/runtime/
npm test -w @google/gemini-cli-core -- src/agent/execution/
npm test -w @google/gemini-cli-core -- src/prompts/promptProvider.test.ts src/prompts/collaboration.test.ts
npm test -w @google/gemini-cli -- src/ui/hooks/useAgentRuntime.test.tsx src/ui/commands/subagentsCommand.test.ts
npm run typecheck
npm run lint
npm run build
```

The new test paths above become runnable when their implementation PRs add them.
Add a deterministic CLI-level integration test for the full root/worker/follow-up
flow using the repository's existing fake-provider fixtures where available.
Before submitting implementation changes, run the repository-required
`npm run preflight`. For this documentation-only plan, validate Markdown and
existing source links; implementation test results are not claimed.

## 13. Deferred extensions

Add these only after the in-process acceptance gates pass:

1. **Checkpoint and restart recovery:** versioned native history/context snapshots,
   agent roster, inbox state, outcomes, cursor state, and reconciliation of
   interrupted external tools. A transcript alone is not a runtime checkpoint.
2. **Full-history fork:** snapshot at a settled execution boundary, preserve native
   tool IDs/signatures, remove inappropriate private state, bound context size,
   and make inheritance explicit in both spawn schema and prompts.
3. **Worktrees:** integrate `WorktreeService` with pinned base commits and explicit
   per-agent execution roots. Avoid the CLI helper's process-wide `chdir()` and
   automatic cleanup when an agent closes. Add an explicit capability and a
   `spawn_agent` workspace-mode option only when provisioning and tool rebinding
   are implemented. The runtime creates/validates the checkout and returns its
   binding; the model requests a supported mode rather than manually improvising
   setup. Reject unavailable modes. Explain that peer edits are not automatically
   visible across worktrees and require commit, patch, or artifact exchange.
   Shared repository metadata and external services still need coordination.
4. **App server:** host the same runtime behind a typed facade for execution after
   terminal disconnect and later reattachment. Add transport authentication,
   connection ownership, approval routing, and durable replay before promising
   background execution.
5. **Remote and structured workers:** adapt A2A/specialist execution to the same
   lifecycle contract without confusing endpoint conversation state with local
   runtime identity or requiring all specialist protocols to change together.

The first implementation milestone is one persistent worker completing two
related assignments, followed by a root that spawns two workers, continues its
own work, receives their addressed results, and reuses one worker for a follow-up.
That milestone exercises the intended mechanism before adding transport or
restart durability.
