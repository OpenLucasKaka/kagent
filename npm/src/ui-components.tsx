import type ReactNamespace from "react";

import type { ApprovalChoice } from "./approval-choice";
import type { CommandMenuState } from "./commands";
import { splitGraphemes } from "./editor";
import { maskSecret, selectedProvider, type ProviderSetupState } from "./provider-setup";
import type { ApprovalRequiredEvent, ProviderSnapshot } from "./protocol";
import type { TranscriptEntry } from "./transcript";
import { terminalGraphemeWidth, terminalSafeText } from "./terminal-text";
import { estimateTextRows } from "./terminal-width";

export type AgentStatus =
  | "starting"
  | "idle"
  | "thinking"
  | "cancelling"
  | "approval"
  | "error";

export type TerminalLayout = {
  columns: number;
  rows: number;
  compact: boolean;
  tooNarrow: boolean;
  horizontalPadding: number;
  commandLimit: number;
  promptColumns: number;
  promptRowLimit: number;
  reservedRows: number;
};

export type PromptViewport = {
  before: string;
  active: string;
  after: string;
  rendered: string;
  prefixClipped: boolean;
  suffixClipped: boolean;
};

export type PromptTerminalCursorControl = {
  position: string;
  restore: string;
};

export function shouldRenderPromptPlaceholder({
  input,
  disabled,
  imeSafe,
}: {
  input: string;
  disabled: boolean;
  imeSafe: boolean;
}): boolean {
  return !input && !disabled && !imeSafe;
}

export function shouldRenderInkPromptCursor({
  input,
  disabled,
  imeSafe,
}: {
  input: string;
  disabled: boolean;
  imeSafe: boolean;
}): boolean {
  return Boolean(input) && !disabled && !imeSafe;
}

type ApprovalLayout = Pick<
  ApprovalRequiredEvent,
  "title" | "target" | "reason" | "details"
> & { showDetails?: boolean };

export const TERMINAL_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function createTerminalLayout(
  columns: number,
  rows: number,
  overlays: {
    approval: boolean | ApprovalLayout;
    commandMenu: boolean | CommandMenuState;
    introVisible?: boolean;
    prompt?: string;
    promptCursor?: number;
  },
): TerminalLayout {
  const safeColumns = Math.max(1, columns || 80);
  const safeRows = Math.max(10, rows || 24);
  const tooNarrow = safeColumns < 20;
  const compact = safeColumns < 56;
  const horizontalPadding = compact ? 0 : 1;
  const defaultCommandLimit = compact ? 4 : 6;
  const headerRows = overlays.introVisible === false ? 0 : compact ? 2 : 3;
  const promptChromeRows = 1;
  const fixedBaseRows = headerRows + promptChromeRows;
  const approvalColumns = Math.max(
    4,
    safeColumns - horizontalPadding * 2 - (compact ? 0 : 2),
  );
  const approvalRows = estimateApprovalRows(overlays.approval, approvalColumns);
  const commandColumns = Math.max(
    4,
    safeColumns - horizontalPadding * 2 - (compact ? 0 : 2),
  );
  const commandExtraRows = estimateCommandExtraRows(
    overlays.commandMenu,
    compact,
    commandColumns,
  );
  const commandCapacity = Math.max(
    1,
    safeRows - 1 - fixedBaseRows - 1 - commandExtraRows - approvalRows,
  );
  const commandLimit = overlays.commandMenu
    ? Math.min(defaultCommandLimit, commandCapacity)
    : defaultCommandLimit;
  const promptColumns = Math.max(4, safeColumns - horizontalPadding * 2 - 2);
  const visibleCommandRows =
    overlays.commandMenu && overlays.commandMenu !== true
      ? Math.min(commandLimit, overlays.commandMenu.options.length)
      : commandLimit;
  const commandRows = overlays.commandMenu
    ? visibleCommandRows + commandExtraRows
    : 0;
  const promptRowLimit = Math.max(
    1,
    Math.min(
      compact ? 4 : 6,
      safeRows - 1 - fixedBaseRows - approvalRows - commandRows,
    ),
  );
  const promptRows = overlays.prompt === undefined
    ? 1
    : estimateTextRows(
        createPromptViewport(
          overlays.prompt,
          overlays.promptCursor ?? splitGraphemes(overlays.prompt).length,
          promptColumns,
          promptRowLimit,
        ).rendered,
        promptColumns,
      );
  const baseRows = fixedBaseRows + promptRows;
  return {
    columns: safeColumns,
    rows: safeRows,
    compact,
    tooNarrow,
    horizontalPadding,
    commandLimit,
    promptColumns,
    promptRowLimit,
    reservedRows: Math.min(
      safeRows - 1,
      baseRows + approvalRows + commandRows,
    ),
  };
}

export function NarrowTerminal({
  React,
  Box,
  Text,
}: RenderProps): ReactNamespace.ReactElement {
  return React.createElement(
    Box,
    { flexDirection: "column" },
    React.createElement(Text, { bold: true, color: "cyan" }, "kagent"),
    React.createElement(Text, { color: "gray", wrap: "wrap" }, "widen terminal"),
  );
}

function estimateApprovalRows(
  approval: boolean | ApprovalLayout,
  columns: number,
): number {
  if (!approval) {
    return 0;
  }
  if (approval === true) {
    return 8;
  }
  const rows = (value: string): number =>
    value ? estimateTextRows(value, columns) : 0;
  const detailRows = approval.showDetails
    ? (approval.details ?? []).reduce(
        (total, detail) => total + rows(`  ${detail}`),
        0,
      )
    : 0;
  const detailMarginRows = approval.showDetails && approval.details?.length ? 1 : 0;
  const reasonRows = approval.showDetails ? rows(approval.reason) : 0;
  return (
    5 +
    rows(approval.title) +
    rows(approval.target) +
    rows("←→ select · enter confirm · d details") +
    detailMarginRows +
    detailRows +
    reasonRows
  );
}

function estimateCommandExtraRows(
  menu: boolean | CommandMenuState,
  compact: boolean,
  columns: number,
): number {
  if (!menu) {
    return 0;
  }
  if (menu === true) {
    return compact ? 3 : 2;
  }
  const helpRows = estimateTextRows(
    "↑↓ choose · tab complete · enter run",
    columns,
  );
  const selected = menu.options[menu.selectedIndex];
  const descriptionRows = compact && selected
    ? estimateTextRows(`  ${selected.description}`, columns)
    : 0;
  return 1 + helpRows + descriptionRows;
}

export function createPromptViewport(
  input: string,
  cursor: number,
  columns: number,
  maxRows: number,
): PromptViewport {
  const characters = splitGraphemes(input);
  const safeCursor = Math.min(Math.max(cursor, 0), characters.length);
  const safeColumns = Math.max(4, columns);
  const safeRows = Math.max(1, maxRows);
  const preserveActiveNewline = safeRows > 1;
  let start = safeCursor;
  let end = Math.min(characters.length, safeCursor + 1);

  while (
    start > 0 &&
    promptViewportRows(
      characters,
      safeCursor,
      start - 1,
      end,
      safeColumns,
      preserveActiveNewline,
    ) <= safeRows
  ) {
    start -= 1;
  }
  while (
    end < characters.length &&
    promptViewportRows(
      characters,
      safeCursor,
      start,
      end + 1,
      safeColumns,
      preserveActiveNewline,
    ) <= safeRows
  ) {
    end += 1;
  }
  return promptViewportParts(
    characters,
    safeCursor,
    start,
    end,
    preserveActiveNewline,
  );
}

export function createPromptTerminalCursorControl({
  input,
  cursor,
  columns,
  maxRows,
  horizontalPadding,
}: {
  input: string;
  cursor: number;
  columns: number;
  maxRows: number;
  horizontalPadding: number;
}): PromptTerminalCursorControl {
  const viewport = createPromptViewport(input, cursor, columns, maxRows);
  const safeColumns = Math.max(4, columns);
  const cursorPosition = textEndPosition(viewport.before, safeColumns);
  const promptRows = estimateTextRows(viewport.rendered, safeColumns);
  const up = Math.max(1, promptRows - cursorPosition.row);
  const right = Math.max(0, horizontalPadding + 2 + cursorPosition.column);
  return {
    position: `${showTerminalCursor()}${moveCursorUp(up)}${moveCursorRight(right)}`,
    restore: `\r${moveCursorDown(up)}`,
  };
}

function promptViewportRows(
  characters: string[],
  cursor: number,
  start: number,
  end: number,
  columns: number,
  preserveActiveNewline: boolean,
): number {
  return estimateTextRows(
    promptViewportParts(
      characters,
      cursor,
      start,
      end,
      preserveActiveNewline,
    ).rendered,
    columns,
  );
}

function promptViewportParts(
  characters: string[],
  cursor: number,
  start: number,
  end: number,
  preserveActiveNewline: boolean,
): PromptViewport {
  const prefixClipped = start > 0;
  const suffixClipped = end < characters.length;
  const rawActive = characters[cursor] || " ";
  const active =
    rawActive === "\n" ? (preserveActiveNewline ? " " : "↵") : rawActive;
  const before = `${prefixClipped ? "…" : ""}${characters
    .slice(start, cursor)
    .join("")}`;
  const after = `${
    rawActive === "\n" && preserveActiveNewline ? "\n" : ""
  }${characters.slice(cursor + 1, end).join("")}${
    suffixClipped ? "…" : ""
  }`;
  return {
    before,
    active,
    after,
    rendered: `${before}${active}${after}`,
    prefixClipped,
    suffixClipped,
  };
}

function textEndPosition(text: string, columns: number): { row: number; column: number } {
  let row = 0;
  let column = 0;
  for (const grapheme of splitGraphemes(text)) {
    if (grapheme === "\n") {
      row += 1;
      column = 0;
      continue;
    }
    const width = Math.max(0, terminalGraphemeWidth(grapheme));
    if (column + width >= columns) {
      row += 1;
      column = 0;
    } else {
      column += width;
    }
  }
  return { row, column };
}

function showTerminalCursor(): string {
  return "\u001b[?25h";
}

function moveCursorUp(rows: number): string {
  return rows > 0 ? `\u001b[${rows}A` : "";
}

function moveCursorDown(rows: number): string {
  return rows > 0 ? `\u001b[${rows}B` : "";
}

function moveCursorRight(columns: number): string {
  return columns > 0 ? `\u001b[${columns}C` : "";
}

export function Header({
  React,
  Box,
  Text,
  compact,
  provider,
  setup,
  workspace,
}: RenderProps & {
  compact: boolean;
  provider: ProviderSnapshot | null;
  setup: boolean;
  workspace: string;
}): ReactNamespace.ReactElement {
  const providerLabel = provider?.configured
    ? `${terminalSafeText(provider.display_name)}${
        provider.model ? ` · ${terminalSafeText(provider.model)}` : ""
      }`
    : "";
  const safeWorkspace = terminalSafeText(workspace);
  if (compact) {
    const compactContext = setup ? "  setup" : ` · ${providerLabel || "local"}`;
    return React.createElement(
      Box,
      { flexDirection: "row", marginBottom: 1, flexShrink: 1 },
      React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"),
      React.createElement(
        Text,
        { color: "gray", wrap: "truncate" },
        compactContext,
      ),
    );
  }
  const sessionLabel = [safeWorkspace, providerLabel].filter(Boolean).join(" · ") || "local session";
  return React.createElement(
    Box,
    { flexDirection: "column", marginBottom: 1 },
    React.createElement(
      Box,
      { flexDirection: "row", flexShrink: 0 },
      React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"),
      React.createElement(Text, { color: "gray" }, setup ? "  setup" : ""),
    ),
    React.createElement(
      Text,
      { color: "gray", wrap: "truncate" },
      sessionLabel,
    ),
  );
}

export function ProviderSetupPanel({
  React,
  Box,
  Text,
  frame,
  setup,
}: RenderProps & { frame: number; setup: ProviderSetupState }): ReactNamespace.ReactElement {
  const option = selectedProvider(setup);
  if (setup.stage === "provider") {
    return React.createElement(
      Box,
      { flexDirection: "column" },
      React.createElement(Text, { bold: true }, "Connect a model provider"),
      React.createElement(
        Box,
        { flexDirection: "column", marginTop: 1 },
        ...setup.options.map((candidate, index) =>
          React.createElement(
            Text,
            {
              key: candidate.provider,
              bold: index === setup.selectedIndex,
              color: index === setup.selectedIndex ? "cyan" : undefined,
            },
            `${index === setup.selectedIndex ? "›" : " "} ${candidate.label}`,
          ),
        ),
      ),
      React.createElement(Text, { color: "gray" }, "↑↓ choose  enter continue  esc quit"),
    );
  }
  if (setup.stage === "saving") {
    return React.createElement(
      Box,
      { flexDirection: "column" },
      React.createElement(Text, { bold: true }, `Connect ${option.label}`),
      React.createElement(
        Text,
        { color: "cyan" },
        `${TERMINAL_SPINNER_FRAMES[frame]} Saving settings`,
      ),
    );
  }

  const field = setupField(setup);
  const displayValue = setup.stage === "api_key" ? maskSecret(setup.editor.value) : setup.editor.value;
  return React.createElement(
    Box,
    { flexDirection: "column" },
    React.createElement(Text, { bold: true }, `Connect ${option.label}`),
    React.createElement(Text, { color: "gray", bold: true }, field.label),
    React.createElement(PromptLine, {
      React,
      Box,
      Text,
      cursor: setup.editor.cursor,
      input: displayValue,
      disabled: false,
      placeholder: field.placeholder,
      compact: true,
    }),
    setup.error ? React.createElement(Text, { color: "red", wrap: "wrap" }, setup.error) : null,
    React.createElement(Text, { color: "gray" }, "enter continue  esc back"),
  );
}

export function MessageList({
  React,
  Box,
  Text,
  messages,
}: RenderProps & { messages: TranscriptEntry[] }) {
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...messages.map((message) => {
      const marker =
        message.role === "user" ? "›" : message.role === "assistant" ? "•" : message.role === "command" ? "·" : "!";
      const color =
        message.role === "user" ? "cyan" : message.role === "system" ? "red" : message.role === "command" ? "gray" : undefined;
      return React.createElement(
        Box,
        { key: message.id, flexDirection: "row", marginBottom: 1 },
        React.createElement(Text, { color, bold: message.role === "user" }, `${marker} `),
        React.createElement(
          Box,
          { flexDirection: "column", flexGrow: 1, flexShrink: 1 },
          message.title ? React.createElement(Text, { bold: true, color }, message.title) : null,
          message.detail
            ? React.createElement(Text, { color: "gray", wrap: "wrap" }, message.detail)
            : null,
          message.text
            ? React.createElement(Text, { color, wrap: "wrap" }, message.text)
            : null,
          message.expanded && message.content
            ? React.createElement(Text, { color: "gray", wrap: "wrap" }, message.content)
            : null,
        ),
      );
    }),
  );
}

export function TranscriptPosition({
  React,
  Text,
  newerCount,
}: StatusRenderProps & { newerCount: number }): ReactNamespace.ReactElement | null {
  if (newerCount <= 0) {
    return null;
  }
  return React.createElement(
    Text,
    { color: "gray" },
    `History · ${newerCount} newer`,
  );
}

export function ApprovalPanel({
  React,
  Box,
  Text,
  approval,
  choice,
  compact,
  showDetails,
}: RenderProps & {
  approval: ApprovalRequiredEvent;
  choice: ApprovalChoice;
  compact: boolean;
  showDetails: boolean;
}) {
  return React.createElement(
    Box,
    { flexDirection: "column", marginY: 1, paddingLeft: compact ? 0 : 2 },
    React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"),
    React.createElement(Text, { wrap: "wrap" }, approval.title),
    approval.target ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target) : null,
    showDetails && approval.details?.length
      ? React.createElement(
          Box,
          { flexDirection: "column", marginTop: 1 },
          ...approval.details.map((detail, index) =>
            React.createElement(
              Text,
              { key: `${index}-${detail}`, color: "cyan", wrap: "wrap" },
              `  ${detail}`,
            ),
          ),
        )
      : null,
    showDetails && approval.reason
      ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
      : null,
    React.createElement(
      Box,
      { flexDirection: "row", marginTop: 1 },
      React.createElement(
        Text,
        { bold: choice === "allow", color: choice === "allow" ? "cyan" : "gray" },
        `${choice === "allow" ? "›" : " "} Allow once`,
      ),
      React.createElement(
        Text,
        {
          bold: choice === "deny",
          color: choice === "deny" ? "yellow" : "gray",
        },
        `${compact ? "  " : "    "}${choice === "deny" ? "›" : " "} Deny`,
      ),
    ),
    React.createElement(Text, { color: "gray" }, "←→ select · enter confirm · d details"),
  );
}

export function CommandPalette({
  React,
  Box,
  Text,
  compact,
  limit,
  menu,
}: RenderProps & { compact: boolean; limit: number; menu: CommandMenuState }) {
  const visibleStart = Math.min(
    Math.max(menu.selectedIndex - limit + 1, 0),
    Math.max(menu.options.length - limit, 0),
  );
  const visibleOptions = menu.options.slice(visibleStart, visibleStart + limit);
  return React.createElement(
    Box,
    { flexDirection: "column", paddingLeft: compact ? 0 : 2, marginTop: 1 },
    ...visibleOptions.map((option, index) => {
      const selected = visibleStart + index === menu.selectedIndex;
      return React.createElement(
        Box,
        { key: option.command, flexDirection: compact ? "column" : "row" },
        React.createElement(
          Text,
          {
            bold: selected,
            color: selected ? "cyan" : "gray",
            wrap: "truncate",
          },
          `${selected ? "›" : " "} ${option.command}`,
        ),
        compact
          ? selected
            ? React.createElement(Text, { color: "gray", wrap: "wrap" }, `  ${option.description}`)
            : null
          : React.createElement(Text, { color: "gray", wrap: "truncate" }, `  ${option.description}`),
      );
    }),
    React.createElement(Text, { color: "gray" }, "↑↓ choose · tab complete · enter run"),
  );
}

export function StatusLine({
  React,
  Text,
  frame,
  elapsedSeconds,
  status,
  statusText,
}: StatusRenderProps & {
  frame: number;
  elapsedSeconds: number;
  status: AgentStatus;
  statusText: string;
}): ReactNamespace.ReactElement | null {
  if (status !== "thinking" && status !== "cancelling" && status !== "starting") {
    return null;
  }
  const label = status === "starting" ? "Starting runtime" : statusText;
  const elapsed = elapsedSeconds > 0 ? ` · ${elapsedSeconds}s` : "";
  return React.createElement(
    Text,
    { color: "cyan" },
    `${TERMINAL_SPINNER_FRAMES[frame]} ${label}${elapsed}`,
  );
}

export function PromptLine({
  React,
  Box,
  Text,
  cursor,
  disabled,
  input,
  placeholder = "Ask kagent",
  compact = false,
  columns = 80,
  maxRows = 6,
  imeSafe = false,
}: RenderProps & {
  cursor: number;
  disabled: boolean;
  input: string;
  placeholder?: string;
  compact?: boolean;
  columns?: number;
  maxRows?: number;
  imeSafe?: boolean;
}) {
  const viewport = createPromptViewport(input, cursor, columns, maxRows);
  const renderPlaceholder = shouldRenderPromptPlaceholder({
    input,
    disabled,
    imeSafe,
  });
  const renderInkCursor = shouldRenderInkPromptCursor({
    input,
    disabled,
    imeSafe,
  });
  const promptContent = renderInkCursor
    ? [
        viewport.before,
        React.createElement(Text, { inverse: true, key: "cursor" }, viewport.active),
        viewport.after,
      ]
    : viewport.rendered;
  return React.createElement(
    Box,
    { flexDirection: "row", marginTop: compact ? 0 : 1, alignItems: "flex-start" },
    React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "),
    input
      ? React.createElement(
          Text,
          { wrap: "wrap" },
          promptContent,
        )
      : React.createElement(Text, { color: "gray" }, renderPlaceholder ? placeholder : ""),
  );
}

function setupField(setup: ProviderSetupState): { label: string; placeholder: string } {
  if (setup.stage === "base_url") {
    return { label: "Base URL", placeholder: "https://api.example.com/v1" };
  }
  if (setup.stage === "model") {
    return { label: "Model", placeholder: "model-id" };
  }
  const required = selectedProvider(setup).api_key_required;
  return {
    label: required ? "API key" : "API key (optional)",
    placeholder: required ? "Paste API key" : "Leave empty for local providers",
  };
}

type RenderProps = {
  React: typeof ReactNamespace;
  Box: ReactNamespace.ElementType;
  Text: ReactNamespace.ElementType;
};

type StatusRenderProps = {
  React: typeof ReactNamespace;
  Text: ReactNamespace.ElementType;
};
