---
name: cognitive-preflight
description: Use when starting or getting stuck on a cognitively demanding task where missing concepts, knowledge, methods, success criteria, resources, or commitment may cause avoidable failure or wasted effort.
---

# Cognitive Preflight

## Core Principle

Expose only prerequisites likely to block the next phase. Prerequisites are a **map, not a gate**: fill, bypass, defer, or use them to reframe. Always return a path forward.

If no known **Necessary** gap remains, enter the task.

## Layers

| Layer | Check | Common pattern |
|---|---|---|
| L1 Language | Terms, notation, assumptions parse precisely? | Quick-fill / Pseudo-gap |
| L2 Knowledge | Relevant facts, examples, theorems available? | Quick-fill / Deep-build |
| L3 Methods | Usable technique, algorithm, experiment, or tool? | Pseudo-gap / Quick-fill |
| L4 Evaluation | Clear what counts as correct, good, or finished? | Reframe trigger |
| L5a Resources | Enough time, compute, data, access, money? | Constraint |
| L5b Commitment | Motivation and risk/emotional cost acceptable? | Reframe / Defer |

Label prerequisites **Necessary** or **Enhancing**. These mappings are priors, not rules.

## Procedure

1. **Define the activity.** Rewrite the goal as an observable output. If the output or evaluation criterion is unclear, trigger an **Early reframe** (short-circuits the audit) before deeper checking.

2. **Build the near dependency frontier.** List only 5–12 prerequisites likely to matter next. Expand only when a dependency is necessary, uncertain, and near-term. Never generate a full syllabus by default.

3. **Estimate readiness from evidence.** Prefer: completed artifact; reproduced derivation/explanation; successful use in a comparable task. Self-report alone is weak evidence. Optionally score 0 unfamiliar; 1 recognize; 2 usable with references; 3 fluent. Scores below 2 are candidate gaps, not blockers.

4. **Classify material gaps:**
   - **Quick-fill:** cheap lookup, definition, example, or derivation.
   - **Deep-build:** sustained learning/practice.
   - **Constraint:** external resource limitation.
   - **Pseudo-gap:** can be bypassed by abstraction, tooling, delegation, approximation, or reformulation.

5. **Choose:** **Fill now**, **Bypass**, **Defer**, or **Reframe**. Reframe when L4 is unclear, the target is not observable, or at least two Necessary gaps are Constraints. Never conclude “not ready” without the cheapest viable path forward.

6. **Set one checkpoint.** Re-run only after repeated uninformative failure, a newly central concept/tool, changed success criteria, a new external constraint, or material task branching. Inspect only newly relevant dependencies.

Prioritize with `risk = P(missing) × cost_if_missing × imminence`; low/medium/high is usually enough.

## Stop Conditions

Stop checking when further analysis would not change the next action. If preflight exceeds 5 minutes for a task under 30 minutes, enter unless a known Necessary blocker remains. If no gap is Necessary, enter immediately. Treat more prerequisite mapping as a hypothesis, not progress.

## Output

```text
Task: <observable target>
Critical prerequisites
- [Lx][Necessary|Enhancing] <item> — <evidence/readiness>
Material gaps
- <gap> → <gap type> → <action>
Entry decision: <enter now / fill first / reframe>
Next checkpoint: <specific trigger>
```