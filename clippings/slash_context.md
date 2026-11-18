Searched "google-gemini/gemini-cli" slash commands "packages/cli" stats OR context
Searched "statsCommand" "packages/cli/src/ui" "gemini-cli"

The `/context` view in your screenshot is a **2D wafer chart (25 × 10 grid = 250 cells)** paired with a categorized token breakdown. Because `gemini-cli` (`@google/gemini-cli`) is built with **TypeScript, React, and [Ink](https://github.com/vadimdemedes/ink)** (a Flexbox layout engine for terminals), you can implement this natively in `packages/cli`.

---

### 1. Anatomy of the Visualization

Before writing code, note three subtle details in how the screenshot renders the data:

1. **Unicode Glyphs by Role:**
   - `⛁` (`\u26C1` / database cylinder): Static/system overhead (**System prompt**, **System tools**, **Skills**, **Subagents**)
   - `◐` (`\u25D0` / circle with left half black): Dynamic conversation turns (**User messages**, **Agent responses**, **Tool calls**)
   - `□` (`\u25A1` / white square): **Free space**
   - `☒` (`\u2612` / ballot box with X): **Checkpoint buffer** (reserved tokens excluded from usable capacity)
2. **Minimum 1-Cell Clamping for Non-Zero Categories:**
   - The grid is `25 columns × 10 rows = 250 cells` (each cell = `0.4%` of the context window).
   - Even though `6.6%` of 250 cells is ~16.5 cells, row 1 in your screenshot has **19 filled cells**. That is because any category with `tokens > 0` is given `Math.max(1, Math.round((tokens / usableLimit) * 250))` cells so small categories (like `689 tokens (0.1%)`) still appear on the grid.

---

### 2. Step-by-Step Implementation in `gemini-cli`

#### Step 1: Categorize & Count Context Tokens
In `gemini-cli`, the active conversation state lives in `GeminiClient` / `GeminiChat` (`packages/core/src/core/client.ts`), while tool declarations live in `ToolRegistry`.

Because calling the remote `countTokens` API 7 separate times on every `/context` command adds latency, inspect the in-memory `Content[]` array and tool declarations locally, then optionally scale the totals to match the last API response's exact `promptTokenCount`:

```typescript
// packages/cli/src/ui/utils/contextUsage.ts
import type { Content, Part } from '@google/genai';

export interface CategoryUsage {
  id: string;
  label: string;
  glyph: '⛁' | '◐';
  color: string;
  tokens: number;
}

export interface ContextUsageSnapshot {
  modelName: string;
  totalLimit: number;       // e.g. 1_048_576 (1.0M)
  checkpointBuffer: number; // e.g. 1_900
  categories: CategoryUsage[];
}

// Fast local estimation (~4 chars per token for English/JSON)
const estimateTokens = (text: string): number =>
  Math.ceil(Buffer.byteLength(text, 'utf8') / 4);

export function analyzeContextUsage(params: {
  modelName: string;
  totalLimit: number;
  systemPromptText: string;
  toolDeclarationsJson: string;
  skillsText: string;
  subagentsText: string;
  history: Content[];
  lastExactPromptTokens?: number;
}): ContextUsageSnapshot {
  let userTokens = 0;
  let agentTokens = 0;
  let toolCallTokens = 0;

  for (const turn of params.history) {
    for (const part of turn.parts ?? []) {
      if ('functionCall' in part && part.functionCall) {
        toolCallTokens += estimateTokens(JSON.stringify(part.functionCall));
      } else if ('functionResponse' in part && part.functionResponse) {
        toolCallTokens += estimateTokens(JSON.stringify(part.functionResponse));
      } else if ('text' in part && part.text) {
        if (turn.role === 'user') userTokens += estimateTokens(part.text);
        else agentTokens += estimateTokens(part.text);
      } else if ('thought' in part && (part as Part & { thought?: string }).thought) {
        agentTokens += estimateTokens(String((part as Part & { thought?: string }).thought));
      }
    }
  }

  const rawCategories: CategoryUsage[] = [
    { id: 'user',        label: 'User messages',   glyph: '◐', color: '#60a5fa', tokens: userTokens },
    { id: 'agent',       label: 'Agent responses', glyph: '◐', color: '#4ade80', tokens: agentTokens },
    { id: 'tools',       label: 'Tool calls',      glyph: '◐', color: '#fb923c', tokens: toolCallTokens },
    { id: 'sys_prompt',  label: 'System prompt',   glyph: '⛁', color: '#94a3b8', tokens: estimateTokens(params.systemPromptText) },
    { id: 'sys_tools',   label: 'System tools',    glyph: '⛁', color: '#94a3b8', tokens: estimateTokens(params.toolDeclarationsJson) },
    { id: 'skills',      label: 'Skills',          glyph: '⛁', color: '#94a3b8', tokens: estimateTokens(params.skillsText) },
    { id: 'subagents',   label: 'Subagents',       glyph: '⛁', color: '#94a3b8', tokens: estimateTokens(params.subagentsText) },
  ];

  // Optional: normalize heuristic counts against exact API promptTokenCount if available
  const estimatedSum = rawCategories.reduce((sum, c) => sum + c.tokens, 0);
  if (params.lastExactPromptTokens && estimatedSum > 0) {
    const scale = params.lastExactPromptTokens / estimatedSum;
    for (const c of rawCategories) {
      c.tokens = Math.round(c.tokens * scale);
    }
  }

  return {
    modelName: params.modelName,
    totalLimit: params.totalLimit,
    checkpointBuffer: 1900,
    categories: rawCategories,
  };
}
```

---

#### Step 2: Build the Ink Wafer Grid & Legend Component
Create an Ink component in `packages/cli/src/ui/components/ContextUsageDisplay.tsx` that lays out the 25×10 grid on the left and the legend on the right using `<Box flexDirection="row">`:

```tsx
// packages/cli/src/ui/components/ContextUsageDisplay.tsx
import React from 'react';
import { Box, Text } from 'ink';
import type { ContextUsageSnapshot } from '../utils/contextUsage.js';

const COLS = 25;
const ROWS = 10;
const TOTAL_CELLS = COLS * ROWS; // 250

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${n}`;
}

export const ContextUsageDisplay: React.FC<{ data: ContextUsageSnapshot }> = ({ data }) => {
  const usableLimit = data.totalLimit;
  const usedTokens = data.categories.reduce((sum, c) => sum + c.tokens, 0);
  const freeTokens = Math.max(0, usableLimit - usedTokens);
  const usedPct = ((usedTokens / usableLimit) * 100).toFixed(1);

  // Build flat array of 250 cells (system categories first or in legend order)
  const cells: Array<{ char: string; color: string }> = [];
  for (const cat of data.categories) {
    if (cat.tokens <= 0) continue;
    const count = Math.max(1, Math.round((cat.tokens / usableLimit) * TOTAL_CELLS));
    for (let i = 0; i < count && cells.length < TOTAL_CELLS; i++) {
      cells.push({ char: cat.glyph, color: cat.color });
    }
  }
  while (cells.length < TOTAL_CELLS) {
    cells.push({ char: '□', color: 'gray' });
  }

  // Chunk into 10 rows of 25 cells
  const gridRows = Array.from({ length: ROWS }, (_, r) =>
    cells.slice(r * COLS, (r + 1) * COLS),
  );

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="gray">└ Context Usage</Text>
      <Box flexDirection="row" marginLeft={2} gap={3}>
        {/* Left: 25x10 Wafer Grid */}
        <Box flexDirection="column">
          {gridRows.map((row, rIdx) => (
            <Text key={rIdx}>
              {row.map((cell, cIdx) => (
                <Text key={cIdx} color={cell.color}>
                  {cell.char}
                </Text>
              ))}
            </Text>
          ))}
        </Box>

        {/* Right: Category Breakdown */}
        <Box flexDirection="column">
          <Text>
            <Text bold>{data.modelName}</Text> • {formatTokens(usedTokens)}/
            {formatTokens(usableLimit)} tokens
          </Text>
          <Text color="gray"> ({usedPct}%)</Text>
          <Text color="blueBright">Token usage by category</Text>

          {data.categories.map((cat) => {
            const pct = ((cat.tokens / usableLimit) * 100).toFixed(1);
            return (
              <Text key={cat.id}>
                <Text color={cat.color}>{cat.glyph}</Text>
                {cat.label}: {formatTokens(cat.tokens)} tokens ({pct}%)
              </Text>
            );
          })}

          <Text color="gray">
            □Free space: {formatTokens(freeTokens)} (
            {((freeTokens / usableLimit) * 100).toFixed(1)}%)
          </Text>
          <Text color="gray">
            ☒Checkpoint buffer: {formatTokens(data.checkpointBuffer)} tokens (not counted in usage)
          </Text>
        </Box>
      </Box>
    </Box>
  );
};
```

---

#### Step 3: Register the `/context` Slash Command
Following the same pattern as `packages/cli/src/ui/commands/statsCommand.ts`:

1. **Create `packages/cli/src/ui/commands/contextCommand.ts`**:
   ```typescript
   import { CommandKind, type SlashCommand } from './types.js';
   import { MessageType } from '../types.js';

   export const contextCommand: SlashCommand = {
     name: 'context',
     description: 'Visualize current context window token usage by category',
     kind: CommandKind.BUILT_IN,
     action: (context) => {
       context.ui.addItem(
         {
           type: MessageType.CONTEXT_USAGE, // Add to MessageType enum in ui/types.ts
         },
         Date.now(),
       );
     },
   };
   ```
2. **Render it in `HistoryItemDisplay.tsx`**:
   In `packages/cli/src/ui/components/HistoryItemDisplay.tsx`, handle `item.type === MessageType.CONTEXT_USAGE` by rendering `<ContextUsageDisplay data={...} />`.
3. **Register in `BuiltinCommandLoader.ts`**:
   Import `contextCommand` in `packages/cli/src/services/BuiltinCommandLoader.ts` and add it to the returned command list alongside `statsCommand` and `memoryCommand`.
   
