Analyzed index.ts:L1-250
Analyzed BuiltinCommandLoader.ts:L120-244
Analyzed environmentContext.ts:L1-111
Analyzed HistoryItemDisplay.tsx:L1-120
Analyzed index.ts:L250-328
Analyzed types.ts:L350-455
Analyzed textUtils.ts:L1-120
Analyzed ToolsList.tsx:L1-51
Analyzed textUtils.ts:L121-287

Here is the complete, end-to-end implementation plan for `D:/codes/gemini-cli`, incorporating the fixes for `estimateTokenCountSync` exports, double-counting prevention, uninitialized chat guards, `<session_context>` classification, and telemetry alignment.

---

### Step 1: Export `tokenCalculation` from `@google/gemini-cli-core`

Currently, [tokenCalculation.ts](file:///D:/codes/gemini-cli/packages/core/src/utils/tokenCalculation.ts#L120-L147) is internal to `packages/core` and not re-exported in [index.ts](file:///D:/codes/gemini-cli/packages/core/src/index.ts#L116-L120).

In [packages/core/src/index.ts](file:///D:/codes/gemini-cli/packages/core/src/index.ts#L116-L120), add:

```ts
export * from './utils/environmentContext.js';
export * from './utils/tokenCalculation.js';
```

---

### Step 2: Define the `context_usage` History Item Type

In [packages/cli/src/ui/types.ts](file:///D:/codes/gemini-cli/packages/cli/src/ui/types.ts#L351-L477):

1. **Add the interfaces and `HistoryItemContextUsage` type** (around line 355):
   ```ts
   export interface ContextCategoryItem {
     name: string;
     tokens: number;
     color: string;
     symbol: '⛁' | '⛃' | '⛶';
   }

   export interface GridCell {
     color?: string;
     symbol: string;
     dim?: boolean;
   }

   export type HistoryItemContextUsage = HistoryItemBase & {
     type: 'context_usage';
     model: string;
     totalTokens: number;
     maxTokens: number;
     categories: ContextCategoryItem[];
     gridRows: GridCell[][]; // 10 rows x 20 cols
   };
   ```

2. **Add `HistoryItemContextUsage` to `HistoryItemWithoutId`** (at [types.ts:422-450](file:///D:/codes/gemini-cli/packages/cli/src/ui/types.ts#L422-L450)):
   ```ts
     | HistoryItemHint
     | HistoryItemSubagent
     | HistoryItemContextUsage;
   ```

3. **Add `CONTEXT_USAGE` to `MessageType`** (at [types.ts:455-477](file:///D:/codes/gemini-cli/packages/cli/src/ui/types.ts#L455-L477)):
   ```ts
     CHAT_LIST = 'chat_list',
     HINT = 'hint',
     CONTEXT_USAGE = 'context_usage',
   }
   ```

---

### Step 3: Create the Ink View Component (`ContextUsageView.tsx`)

Create `D:/codes/gemini-cli/packages/cli/src/ui/components/views/ContextUsageView.tsx`:

```tsx
/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import type React from 'react';
import { Box, Text } from 'ink';
import type { HistoryItemContextUsage } from '../../types.js';

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${n}`;
}

export const ContextUsageView: React.FC<
  Omit<HistoryItemContextUsage, 'type'>
> = ({ model, totalTokens, maxTokens, categories, gridRows }) => {
  const totalPct =
    maxTokens > 0 ? ((totalTokens / maxTokens) * 100).toFixed(1) : '0.0';

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1} marginBottom={1}>
      <Text bold>└ Context Usage</Text>
      <Box flexDirection="row" gap={2}>
        {/* Left: 10x20 Wafer Grid */}
        <Box flexDirection="column" flexShrink={0}>
          {gridRows.map((row, rIdx) => (
            <Box key={rIdx} flexDirection="row">
              {row.map((cell, cIdx) => (
                <Text key={cIdx} color={cell.color} dimColor={cell.dim}>
                  {cell.symbol}{' '}
                </Text>
              ))}
            </Box>
          ))}
        </Box>

        {/* Right: Category Breakdown Legend */}
        <Box flexDirection="column" flexShrink={0}>
          <Text dimColor>
            {model} · {formatTokens(totalTokens)}/{formatTokens(maxTokens)}{' '}
            tokens ({totalPct}%)
          </Text>
          <Text italic dimColor>
            Token usage by category
          </Text>
          {categories.map((cat, idx) => {
            const pct =
              maxTokens > 0
                ? ((cat.tokens / maxTokens) * 100).toFixed(1)
                : '0.0';
            const isFree = cat.name === 'Free space';
            return (
              <Box key={idx}>
                <Text color={isFree ? undefined : cat.color} dimColor={isFree}>
                  {cat.symbol}
                </Text>
                <Text> {cat.name}: </Text>
                <Text dimColor>
                  {formatTokens(cat.tokens)}
                  {isFree ? '' : ' tokens'} ({pct}%)
                </Text>
              </Box>
            );
          })}
        </Box>
      </Box>
    </Box>
  );
};
```

---

### Step 4: Render `ContextUsageView` in `HistoryItemDisplay.tsx`

In [packages/cli/src/ui/components/HistoryItemDisplay.tsx](file:///D:/codes/gemini-cli/packages/cli/src/ui/components/HistoryItemDisplay.tsx#L38-L255):

1. **Import `ContextUsageView`** (around line 39):
   ```tsx
   import { ChatList } from './views/ChatList.js';
   import { ContextUsageView } from './views/ContextUsageView.js';
   ```

2. **Render for `type === 'context_usage'`** (at [HistoryItemDisplay.tsx:251-254](file:///D:/codes/gemini-cli/packages/cli/src/ui/components/HistoryItemDisplay.tsx#L251-L254)):
   ```tsx
         {itemForDisplay.type === 'chat_list' && (
           <ChatList chats={itemForDisplay.chats} />
         )}
         {itemForDisplay.type === 'context_usage' && (
           <ContextUsageView {...itemForDisplay} />
         )}
       </Box>
     );
   };
   ```

---

### Step 5: Implement `/context` Command (`contextCommand.ts`)

Create `D:/codes/gemini-cli/packages/cli/src/ui/commands/contextCommand.ts`:

```ts
/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  tokenLimit,
  estimateTokenCountSync,
  getCoreSystemPrompt,
  resolveModel,
  getDisplayString,
  uiTelemetryService,
} from '@google/gemini-cli-core';
import {
  CommandKind,
  type CommandContext,
  type SlashCommand,
} from './types.js';
import {
  MessageType,
  type ContextCategoryItem,
  type GridCell,
} from '../types.js';

const GRID_ROWS = 10;
const GRID_COLS = 20;
const TOTAL_CELLS = GRID_ROWS * GRID_COLS; // 200 cells

export const contextCommand: SlashCommand = {
  name: 'context',
  description: 'Visualize current context window token usage by category',
  kind: CommandKind.BUILT_IN,
  autoExecute: true,
  isSafeConcurrent: true,
  action: (context: CommandContext) => {
    const agentContext = context.services.agentContext;
    const config = agentContext?.config;
    const geminiClient = agentContext?.geminiClient;

    if (!config || !geminiClient) {
      context.ui.addItem({
        type: MessageType.ERROR,
        text: 'Agent context is unavailable.',
      });
      return;
    }

    // Resolve active model and token limit
    const activeModel = resolveModel(
      config.getActiveModel(),
      config.getGemini31LaunchedSync?.() ?? false,
      false,
      config.getHasAccessToPreviewModel?.() ?? true,
      config,
      config.hasGemini35FlashGAAccess?.() ?? false,
    );
    const maxTokens = tokenLimit(activeModel);
    const displayModel = getDisplayString(activeModel);

    // 1. Estimate conversation turns & chronological cell colors
    let userTokens = 0;
    let agentTokens = 0;
    let toolTokens = 0;
    let sessionSetupTokens = 0;
    const turnSegments: Array<{
      tokens: number;
      color: string;
      symbol: string;
    }> = [];

    const history = geminiClient.isInitialized()
      ? geminiClient.getHistory()
      : [];

    for (let i = 0; i < history.length; i++) {
      const content = history[i];
      for (const part of content.parts ?? []) {
        const t = estimateTokenCountSync([part]);
        if (t <= 0) continue;

        // Classify initial <session_context> injection as System prompt overhead
        if (
          i === 0 &&
          content.role === 'user' &&
          typeof part.text === 'string' &&
          part.text.includes('<session_context>')
        ) {
          sessionSetupTokens += t;
          continue;
        }

        if (part.functionCall || part.functionResponse) {
          toolTokens += t;
          turnSegments.push({ tokens: t, color: 'yellow', symbol: '⛁' });
        } else if (content.role === 'user') {
          userTokens += t;
          turnSegments.push({ tokens: t, color: 'blueBright', symbol: '⛁' });
        } else {
          agentTokens += t;
          turnSegments.push({ tokens: t, color: 'green', symbol: '⛁' });
        }
      }
    }

    // 2. Estimate static overhead (System prompt, Tools, Skills, Subagents)
    const skills = config.getSkillManager()?.getSkills() ?? [];
    const skillsTokens = skills.length
      ? estimateTokenCountSync([
          {
            text: skills
              .map(
                (s) =>
                  `<skill>\n  <name>${s.name}</name>\n  <description>${s.description}</description>\n  <location>${s.location}</location>\n</skill>`,
              )
              .join('\n'),
          },
        ])
      : 0;

    const agents = config.getAgentRegistry()?.getAllDefinitions() ?? [];
    const subagentsTokens = agents.length
      ? estimateTokenCountSync([
          {
            text: agents
              .map(
                (a) =>
                  `<subagent>\n  <name>${a.name}</name>\n  <description>${a.description}</description>\n</subagent>`,
              )
              .join('\n'),
          },
        ])
      : 0;

    const sysPromptText = getCoreSystemPrompt(
      config,
      config.getSystemInstructionMemory(),
    );
    const rawSystemPromptTokens =
      estimateTokenCountSync([{ text: sysPromptText }]) + sessionSetupTokens;
    // Subtract skills & subagents since getCoreSystemPrompt embeds both
    let systemPromptTokens = Math.max(
      0,
      rawSystemPromptTokens - skillsTokens - subagentsTokens,
    );

    const declarations =
      agentContext.toolRegistry?.getFunctionDeclarations(activeModel) ?? [];
    let systemToolsTokens = declarations.length
      ? estimateTokenCountSync([{ text: JSON.stringify(declarations) }])
      : 0;

    let scaledSkillsTokens = skillsTokens;
    let scaledSubagentsTokens = subagentsTokens;

    const rawTotalTokens =
      userTokens +
      agentTokens +
      toolTokens +
      systemPromptTokens +
      systemToolsTokens +
      scaledSkillsTokens +
      scaledSubagentsTokens;

    // Align with exact promptTokenCount from the last API turn when available
    const lastExactPromptTokens = uiTelemetryService.getLastPromptTokenCount();
    if (lastExactPromptTokens > 0 && rawTotalTokens > 0) {
      const scale = lastExactPromptTokens / rawTotalTokens;
      userTokens = Math.round(userTokens * scale);
      agentTokens = Math.round(agentTokens * scale);
      toolTokens = Math.round(toolTokens * scale);
      systemPromptTokens = Math.round(systemPromptTokens * scale);
      systemToolsTokens = Math.round(systemToolsTokens * scale);
      scaledSkillsTokens = Math.round(scaledSkillsTokens * scale);
      scaledSubagentsTokens = Math.round(scaledSubagentsTokens * scale);
      for (const seg of turnSegments) {
        seg.tokens = seg.tokens * scale;
      }
    }

    const totalTokens =
      userTokens +
      agentTokens +
      toolTokens +
      systemPromptTokens +
      systemToolsTokens +
      scaledSkillsTokens +
      scaledSubagentsTokens;
    const freeTokens = Math.max(0, maxTokens - totalTokens);

    const categories: ContextCategoryItem[] = [
      {
        name: 'User messages',
        tokens: userTokens,
        color: 'blueBright',
        symbol: '⛁',
      },
      {
        name: 'Agent responses',
        tokens: agentTokens,
        color: 'green',
        symbol: '⛁',
      },
      {
        name: 'Tool calls',
        tokens: toolTokens,
        color: 'yellow',
        symbol: '⛁',
      },
      {
        name: 'System prompt',
        tokens: systemPromptTokens,
        color: 'gray',
        symbol: '⛃',
      },
      {
        name: 'System tools',
        tokens: systemToolsTokens,
        color: 'gray',
        symbol: '⛃',
      },
      {
        name: 'Skills',
        tokens: scaledSkillsTokens,
        color: 'gray',
        symbol: '⛃',
      },
      {
        name: 'Subagents',
        tokens: scaledSubagentsTokens,
        color: 'gray',
        symbol: '⛃',
      },
      {
        name: 'Free space',
        tokens: freeTokens,
        color: 'gray',
        symbol: '⛶',
      },
    ];

    // 3. Build 200-cell (10x20) chronological grid
    const tokensPerCell = maxTokens / TOTAL_CELLS;
    const cells: GridCell[] = [];

    const staticOverheadTokens =
      systemPromptTokens +
      systemToolsTokens +
      scaledSkillsTokens +
      scaledSubagentsTokens;

    const allSegments = [
      ...(staticOverheadTokens > 0
        ? [{ tokens: staticOverheadTokens, color: 'gray', symbol: '⛃' }]
        : []),
      ...turnSegments,
    ];

    let acc = 0;
    let lastNonEmptySeg: { color: string; symbol: string } | undefined;
    for (const seg of allSegments) {
      if (seg.tokens <= 0) continue;
      lastNonEmptySeg = seg;
      acc += seg.tokens;
      while (acc >= tokensPerCell && cells.length < TOTAL_CELLS) {
        cells.push({ color: seg.color, symbol: seg.symbol });
        acc -= tokensPerCell;
      }
    }
    if (acc > 0 && cells.length < TOTAL_CELLS && lastNonEmptySeg) {
      cells.push({
        color: lastNonEmptySeg.color,
        symbol: lastNonEmptySeg.symbol,
      });
    }
    while (cells.length < TOTAL_CELLS) {
      cells.push({ symbol: '⛶', dim: true });
    }

    const gridRows: GridCell[][] = [];
    for (let r = 0; r < GRID_ROWS; r++) {
      gridRows.push(cells.slice(r * GRID_COLS, (r + 1) * GRID_COLS));
    }

    context.ui.addItem({
      type: MessageType.CONTEXT_USAGE,
      model: displayModel,
      totalTokens,
      maxTokens,
      categories,
      gridRows,
    });
  },
};
```

---

### Step 6: Register `contextCommand` in `BuiltinCommandLoader.ts`

In [packages/cli/src/services/BuiltinCommandLoader.ts](file:///D:/codes/gemini-cli/packages/cli/src/services/BuiltinCommandLoader.ts#L29-L137):

1. **Import `contextCommand`** (around line 30):
   ```ts
   import { compressCommand } from '../ui/commands/compressCommand.js';
   import { contextCommand } from '../ui/commands/contextCommand.js';
   ```

2. **Add `contextCommand` to `allDefinitions`** (around line 136):
   ```ts
         clearCommand,
         commandsCommand,
         compressCommand,
         contextCommand,
         copyCommand,
   ```

---

