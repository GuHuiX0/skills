# CODEQUEST — END-TO-END GAME IMPLEMENTATION BRIEF

## ROLE

You are acting as a small senior game development team consisting of:

- Creative Director
- Game Designer
- Interaction Designer
- Visual Designer
- Senior Frontend Engineer
- Gameplay Systems Engineer
- QA Engineer

Your task is to DESIGN, IMPLEMENT, TEST, and POLISH a complete, playable browser game called **CodeQuest**.

Do not produce a concept document and stop. Deliver the working application in the existing project workspace.

Make reasonable product and implementation decisions autonomously. Do not ask unnecessary clarification questions.

Prioritize a polished, enjoyable, coherent vertical slice over a large collection of incomplete features.

---

# 1. PRODUCT VISION

CodeQuest is a browser-native puzzle and exploration game that teaches players how software systems work.

The player is a systems engineer entering a damaged digital infrastructure.

The digital world represents a real, small software system.

Players must understand its architecture, trace execution paths, inspect code, identify bugs, and restore broken functionality.

**Core philosophy: The player changes the game world by understanding the software system behind it.**

This must feel like a real puzzle game, NOT:
- A SaaS dashboard with gamification.
- An AI chatbot with a coding interface.
- A multiple-choice quiz application.
- A generic coding tutorial.
- A static flowchart with clickable nodes.

The player should spend most of their time experimenting, observing, investigating, connecting, and repairing systems.

Generative AI is explicitly OUT OF SCOPE for this version.

All game content must be deterministic, authored, and testable.

---

# 2. GAME CONCEPT

Game title: CODEQUEST

Subtitle: Restore the Network

Genre:
- Systems puzzle
- Investigation
- Exploration
- Light programming

Setting:

A fictional industrial network has experienced a catastrophic system failure.

The network is divided into interconnected sectors.

Each sector represents part of an application:

- Interface Terminal
- State Reactor
- Authentication Gateway
- API Relay
- Data Vault

The player gradually discovers how the system operates and restores its functionality.

The world map should visually resemble an elegant industrial wiring diagram.

Avoid fantasy RPG clichés.

No characters, monsters, swords, or conventional combat.

The conflict is between the player and a malfunctioning system.

---

# 3. CORE GAMEPLAY LOOP

The main gameplay loop:

1. Observe a malfunction.
2. Explore the affected system.
3. Inspect components and available evidence.
4. Form a hypothesis about the failure.
5. Interact with the system to test the hypothesis.
6. Repair the system.
7. Execute a validation test.
8. Observe the world change.
9. Unlock the next area.

Every successful action should cause meaningful visual feedback in the environment.

The player should never receive a reward solely for clicking through explanatory text.

Correct understanding and system manipulation must drive progression.

---

# 4. PLAYABLE VERTICAL SLICE

Build ONE complete campaign:

**CHAPTER 01 — THE BROKEN LOGIN NETWORK**

Target playtime: approximately 10–15 minutes for a first-time player.

The campaign contains four connected phases.

## Phase 1 — Discover the Network

The player enters a partially powered system map.

Visible modules:
- Login Terminal
- Auth Gateway
- API Relay
- User Database

Some connections are unknown or disabled.

Player interactions:
- Click a module to inspect it.
- Read concise module descriptions.
- View available logs.
- Follow visible connections.
- Reveal unknown connections by inspecting evidence.

The system map should progressively reveal information.

Do not overwhelm the player with every detail immediately.

Goal:
Discover the entry point of the login request and the next component it communicates with.

## Phase 2 — Trace the Signal

The player must trace a login request from source to destination.

Expected execution path:

Login Terminal → Auth Gateway → API Relay → User Database

Include one plausible but incorrect route through a Cache Node.

Gameplay:
- Select a starting node.
- Connect nodes in order.
- Execute a signal simulation.
- Animate a signal moving through the selected route.
- Display an error when the route is invalid.
- Give a meaningful clue without revealing the answer.

The player should be able to retry.

The correct route must be derived from inspectable evidence such as logs or module interfaces, not from random guessing.

Goal:
Deliver the signal through the correct execution path.

## Phase 3 — Debug the Authentication Machine

The player reaches an authentication machine containing a logic bug.

The machine receives user records with roles.

Expected behavior:
- Admin users are granted privileged access.
- Regular users receive standard access.

Initial bug:
A conditional expression incorrectly reverses the routing behavior.

Player interactions:
- Observe the machine processing user records.
- Run the simulation.
- Inspect the rule controlling the machine.
- Edit the relevant condition.
- Run the simulation again.
- Compare actual and expected output.

The player must understand the bug before repairing it.

Implement a lightweight in-game logic editor.

The editor can initially constrain the editable expression to a safe set of operators and values.

Do not require users to type an entire application from scratch.

Correctness must be established by deterministic test cases, including multiple input records.

Goal:
Fix the logic so every test record is routed correctly.

## Phase 4 — Restore the System

Once the signal path and authentication logic are repaired:

- The previously disabled network comes online.
- Connections become active.
- The system map visibly changes.
- The Data Vault unlocks.
- The player receives a completion report.

Include a short final transfer challenge:

Present a different but structurally similar authorization scenario.

The player must identify the correct logical behavior without step-by-step guidance.

This is important: measure whether the player learned a transferable concept rather than memorizing one solution.

---

# 5. GAME MECHANICS

Implement the following:

## 5.1 Interactive System Map

The map is the main game surface.

Requirements:
- Pan and zoom if needed.
- Clickable nodes.
- Clearly differentiated node states.
- Visible connections.
- Animated signal traversal.
- Locked and unlocked areas.
- Hover and selected states.
- Smooth camera focus or viewport transitions.

The system map must occupy most of the primary screen area.

Use React Flow or a suitable SVG/Canvas implementation.

Do not build the entire game as a conventional form-based UI.

## 5.2 System Inspector

When the player selects a node, display a contextual inspection panel.

Possible information:
- Node name
- System role
- Input ports
- Output ports
- Relevant logs
- Code snippet
- Current machine state

The panel should feel like an industrial diagnostic console.

Use concise, purposeful language.

## 5.3 Signal Simulation

Model the signal as an actual stateful event moving through a graph.

A signal must have:
- Current node
- Intended destination
- Traversed path
- Status
- Error state if invalid

Represent simulation state separately from rendering.

Do not implement the animation as a purely decorative effect.

The graph validator should determine the actual result.

## 5.4 Debugging Mechanic

Implement a deterministic authorization-rule interpreter.

For example:

role === "admin"

The player should be able to modify the rule using a constrained interface.

Each change must affect simulated machine behavior.

The machine must support:
- Reset
- Run
- Inspect inputs
- Inspect outputs
- View failed cases
- Validate solution

Successful tests must result from executing the configured rule.

Never award completion simply because the player clicked a predetermined button.

## 5.5 Exploration Progression

Track:
- Discovered nodes
- Discovered connections
- Completed missions
- Unlocked areas
- Used hints
- Validation results

Persist progress with localStorage.

Provide a Reset Campaign control.

## 5.6 Contextual Hints

Implement three hint levels:

Level 1: Suggest what to investigate.

Level 2: Narrow attention to the relevant component or behavior.

Level 3: Explain the underlying concept, without automatically completing the task.

Hints should be manually authored for this version.

Do not use LLM calls.

---

# 6. ART DIRECTION — CRITICAL

The game must have a cohesive, restrained, premium industrial visual language.

Visual inspiration:
- SHENZHEN I/O: dense but readable technical systems.
- Opus Magnum: satisfying mechanical cause-and-effect.
- Mini Metro: strong information hierarchy and elegant networks.
- High-quality industrial control interfaces.
- Minimalist strategy and automation games.

Use the references as general art-direction inspiration only. Do not copy their copyrighted assets or layouts.

## Desired visual character

- Industrial
- Precise
- Functional
- Tactile
- Slightly retro-futuristic
- Quietly sophisticated
- Highly readable
- Distinctive without excessive decoration

The interface should look like an intentionally designed indie game.

It must NOT look like a generated AI SaaS landing page.

## STRICT VISUAL PROHIBITIONS

DO NOT USE:

- CSS gradients of any kind.
- Purple-blue gradient backgrounds.
- Neon glow effects.
- Glassmorphism.
- Backdrop blur panels.
- Excessive box shadows.
- Rainbow accent colors.
- Giant rounded cards.
- Floating generic dashboard widgets.
- Decorative particle backgrounds.
- Arbitrary glowing circles.
- Oversized marketing headlines.
- Emoji as core interface artwork.
- Generic AI robot imagery.
- Generic chat bubbles.
- Decorative graphs unrelated to gameplay.
- Random animation without gameplay meaning.
- Unnecessary visual effects.

No gradients anywhere in the interface.

Do not use gradient fills in SVG either.

## Color palette

Use these exact initial design tokens:

Background:
#171A1C

Surface:
#24282B

Elevated Surface:
#303538

Primary Text:
#E5E0D5

Secondary Text:
#A9B0AF

Signal / Active:
#D6A15D

Success / Restored:
#8AA69B

Error:
#B86F64

Border:
#4D5354

Use colors semantically.

Amber is for active electrical signals or actionable states.

Green is for successfully restored infrastructure.

Red is for errors and failures.

Do not randomly assign colors to components.

## Typography

Use a disciplined typographic system.

Suggested fonts:
- IBM Plex Sans or another clean technical sans-serif.
- IBM Plex Mono for technical identifiers and code.

Avoid unnecessarily mixing several font families.

Use clear hierarchy and compact technical labels.

Prefer typography that resembles a precision instrument interface.

## Component geometry

- Border radius: 2–6px for most UI surfaces.
- Borders: 1px.
- Shadows: none by default.
- Spacing based on an 8px grid.
- Flat color surfaces.
- Strong alignment.
- Consistent line thickness.
- Compact, deliberate information density.

## Map styling

The world map should resemble a carefully designed electrical schematic.

Nodes:
- Geometrically consistent.
- Labeled clearly.
- Distinct active, inactive, damaged, and selected states.
- Small enough to show relationships.
- Large enough to click comfortably.

Connections:
- Thin, clean lines.
- Orthogonal routing where practical.
- Animated signals that visibly follow connection paths.
- No spaghetti graph layouts.

Background:
- Flat dark surface.
- Optional extremely subtle technical grid.
- No gradient.
- No atmospheric blur.

## Motion design

Animations must communicate:
- Current signal location.
- Machine activation.
- Failure.
- Successful restoration.
- Newly unlocked connections.
- State transitions.

Target durations:
- UI response: 100–200ms.
- Node activation: 150–300ms.
- Signal traversal: 400–900ms depending on path length.
- Major restoration event: 600–1200ms.

Use ease-out or linear motion as appropriate.

Avoid excessive spring animations and arbitrary bouncing.

Honor prefers-reduced-motion.

---

# 7. INTERACTION DESIGN

This must be a playable environment.

Every major UI element must have meaningful behavior.

Examples:

Click node → inspect its state.

Click connection → view the relationship.

Run signal → animate actual execution.

Change rule → alter machine behavior.

Run tests → display real deterministic results.

Complete mission → unlock the next system.

Reset → restore the initial state.

Do not leave placeholder buttons.

Do not create nonfunctional controls merely to make the interface appear complete.

The user should understand the goal without reading a lengthy onboarding document.

Use progressive disclosure.

At the beginning, show only:
- Current objective
- Main system map
- A small interaction hint

Reveal technical details as the player investigates.

---

# 8. TECHNICAL IMPLEMENTATION

Preferred stack:

- React
- TypeScript
- Vite
- Tailwind CSS
- React Flow / @xyflow/react
- Zustand or a lightweight state machine
- Vitest
- Playwright

Use the existing project stack if a compatible application is already initialized.

Do not replace working infrastructure unnecessarily.

No backend is required for the initial version.

No database is required.

No generative AI.

No WebContainer integration is required for this first version.

The initial game is a deterministic browser simulation.

Keep the architecture extensible so a future version can connect the graph to a real repository and replace simulated logic with a runtime executing actual code.

## Suggested source structure

src/
  app/
    App.tsx
  game/
    engine/
      graph.ts
      signal.ts
      validation.ts
      progression.ts
    content/
      chapter01.ts
    state/
      gameStore.ts
    types/
      game.ts
  components/
    SystemMap.tsx
    SystemNode.tsx
    SignalRenderer.tsx
    InspectorPanel.tsx
    MissionPanel.tsx
    LogicEditor.tsx
    TestConsole.tsx
    CompletionScreen.tsx
  styles/
    tokens.css
    global.css

Separate game logic from UI rendering.

Do not hardcode mission completion into visual components.

## Core domain models

Design typed structures for:

SystemNode
SystemEdge
Signal
Mission
MissionObjective
Machine
MachineRule
TestCase
ValidationResult
PlayerProgress
GameEvent

Use a deterministic game state transition model.

The game state should be inspectable and testable.

---

# 9. USER EXPERIENCE REQUIREMENTS

Primary target:
Desktop browsers, especially Chromium.

Support widths from approximately 1024px upward.

At smaller widths:
- Preserve usability.
- Allow panels to stack or become collapsible.
- Do not force an unreadable full-width graph.

Keyboard:
- Escape closes panels.
- Enter confirms appropriate interactions.
- R resets a simulation when relevant.

Accessibility:
- Accessible labels for actionable nodes.
- Visible keyboard focus.
- Adequate text contrast.
- Reduced-motion support.
- Do not rely on color alone to communicate game state.

Audio is optional and should be omitted if it compromises schedule or quality.

---

# 10. GAME FEEL

The player must experience a cycle of:

Curiosity → Investigation → Hypothesis → Experiment → Discovery → Mastery.

Prioritize moments of immediate cause and effect.

Examples:

A signal travels across the network, reaches a defective node, and stops.

A faulty conditional sends the wrong packet into a restricted zone.

A corrected rule causes the machine to route every packet successfully.

An entire network sector powers up after successful repair.

These environmental responses should be more satisfying than receiving XP.

Rewards should emphasize meaningful system restoration.

A small completion score is acceptable.

Avoid overloading the game with badges, coins, currencies, and leaderboards.

---

# 11. QUALITY BAR

The application must feel like one coherent game.

Not a collection of unrelated mini demos.

Requirements:

1. Consistent visual design across all screens.
2. Clear player objective at every stage.
3. A functional main map.
4. Real interactive mechanics.
5. Deterministic puzzle evaluation.
6. Visible consequences for correct and incorrect actions.
7. Persistent progression.
8. A satisfying campaign ending.
9. No dead buttons.
10. No broken navigation.
11. No unnecessary placeholder content.
12. No runtime errors.

Every mission must be completable from the initial game state using only information available in the UI.

Every failure state must have a recovery path.

The player must never become permanently stuck due to an invalid UI state.

---

# 12. TESTING REQUIREMENTS

Create unit tests for:

- Graph path validation.
- Invalid signal routes.
- Valid signal routes.
- Rule evaluation.
- Authorization test cases.
- Mission completion.
- Progress unlock conditions.
- State reset behavior.

Create Playwright end-to-end tests for:

1. Starting a new campaign.
2. Inspecting a module.
3. Discovering a connection.
4. Submitting an incorrect signal route.
5. Recovering from the error.
6. Completing the correct route.
7. Running the broken authentication machine.
8. Correcting its logic.
9. Passing validation.
10. Unlocking the final area.
11. Completing the campaign.
12. Reloading and restoring saved progress.

Run the app locally and inspect its rendered interface through a browser if browser automation is available.

Inspect actual screenshots rather than trusting the source code alone.

Test at least:
- 1440 × 900
- 1280 × 800
- 1024 × 768

Check:
- Layout overflow.
- Text clipping.
- Interaction target sizes.
- Visual hierarchy.
- Contrast.
- Color consistency.
- Responsiveness.
- Console errors.
- Gameplay completion.

Fix issues found during testing.

---

# 13. VISUAL SELF-CRITIQUE

Before finalizing, evaluate the design against the following questions.

1. Does this look like an indie systems puzzle game or a generic AI dashboard?
2. Does the system map dominate the experience?
3. Are the game interactions visually obvious?
4. Is every color used for a specific reason?
5. Could the interface be simplified without losing important information?
6. Are we using visual effects to hide weak information architecture?
7. Are the animation and feedback directly connected to system behavior?
8. Is the typography consistent?
9. Does the interface have a recognizable visual identity?
10. Is the game itself enjoyable without an AI chatbot?

If the interface resembles a generic AI-generated SaaS dashboard, redesign it.

Do not merely change the colors.

Reconsider the layout, interaction model, visual hierarchy, and component geometry.

---

# 14. IMPLEMENTATION WORKFLOW

Execute the project in this order.

STEP 1 — Inspect the repository and determine the current implementation state.

STEP 2 — Implement the design tokens and global visual foundation.

STEP 3 — Implement the deterministic game data model and state transitions.

STEP 4 — Implement the interactive system map.

STEP 5 — Implement node inspection and evidence discovery.

STEP 6 — Implement signal simulation and route validation.

STEP 7 — Implement the debugging machine and rule evaluation.

STEP 8 — Implement progression, unlocks, and completion.

STEP 9 — Add concise instructional copy and feedback animations.

STEP 10 — Implement tests.

STEP 11 — Run the application and inspect the UI.

STEP 12 — Refine visual quality, layout, and game feel.

STEP 13 — Verify the full campaign is playable from beginning to end.

Do not stop at planning or scaffolding.

Prefer a smaller finished product over a broader unfinished implementation.

---

# 15. DEFINITION OF DONE

The project is complete only when:

- The application starts with a documented command.
- The player can begin a new campaign.
- The system map is interactive.
- The player can inspect meaningful evidence.
- The signal puzzle is functional.
- Incorrect paths produce failure feedback.
- The authentication machine executes actual deterministic logic.
- Changing that logic changes the result.
- The player can repair the machine.
- Tests validate success.
- Completing missions unlocks the world.
- Progress persists across reloads.
- The final completion screen works.
- The interface follows the specified visual system.
- No gradients or glow effects have been introduced.
- Automated tests pass.
- The main flow has been manually or browser-automatically verified.

At the end, provide:

1. A concise implementation summary.
2. The final file structure.
3. Instructions to run the game.
4. A description of the implemented gameplay.
5. Automated test results.
6. Any limitations or remaining issues.
7. Screenshots if the environment supports them.

Do not claim a test passed unless it was actually executed.

Do not claim the full campaign works without verifying the completion path.

## FINAL DIRECTIVE

Build a polished, deterministic, browser-native systems puzzle game.

The quality benchmark is not how many features you implement.

It is whether a new player can open the game, understand their objective, investigate the network, repair a meaningful system failure, and feel the satisfaction of restoring a system through reasoning.

**Make it feel designed, not generated.**
