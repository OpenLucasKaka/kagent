import type ReactNamespace from "react";

import type { CommandMenuState } from "./commands";
import { splitGraphemes } from "./editor";
import { maskSecret, selectedProvider, type ProviderSetupState } from "./provider-setup";
import type { ApprovalRequiredEvent, ProviderSnapshot } from "./protocol";
import type { TranscriptEntry } from "./transcript";
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
  horizontalPadding: number;
  commandLimit: number;
  reservedRows: number;
};

export const TERMINAL_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function createTerminalLayout(
  columns: number,
  rows: number,
  overlays: { approval: boolean; commandMenu: boolean; prompt?: string },
): TerminalLayout {
  const safeColumns = Math.max(20, columns || 80);
  const safeRows = Math.max(10, rows || 24);
  const compact = safeColumns < 56;
  const horizontalPadding = compact ? 0 : 1;
  const commandLimit = compact ? 4 : 6;
  const promptColumns = Math.max(4, safeColumns - horizontalPadding * 2 - 2);
  const promptRows = overlays.prompt
    ? estimateTextRows(overlays.prompt, promptColumns)
    : 1;
  const baseRows = 5 + Math.max(0, promptRows - 1);
  const approvalRows = overlays.approval ? (compact ? 6 : 7) : 0;
  const commandRows = overlays.commandMenu ? commandLimit + 2 : 0;
  return {
    columns: safeColumns,
    rows: safeRows,
    compact,
    horizontalPadding,
    commandLimit,
    reservedRows: baseRows + approvalRows + commandRows,
  };
}

export function Header({
  React,
  Box,
  Text,
  compact,
  provider,
  setup,
}: RenderProps & {
  compact: boolean;
  provider: ProviderSnapshot | null;
  setup: boolean;
}): ReactNamespace.ReactElement {
  const providerLabel = provider?.configured
    ? `${provider.display_name}${provider.model ? ` · ${provider.model}` : ""}`
    : "";
  return React.createElement(
    Box,
    { flexDirection: compact ? "row" : "column", marginBottom: 1 },
    React.createElement(
      Box,
      { flexDirection: "row", flexShrink: 0 },
      React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"),
      React.createElement(Text, { color: "gray" }, setup ? "  setup" : ""),
    ),
    providerLabel
      ? React.createElement(
          Text,
          { color: "gray", wrap: "truncate" },
          compact ? ` · ${providerLabel}` : providerLabel,
        )
      : null,
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
  compact,
  showDetails,
}: RenderProps & {
  approval: ApprovalRequiredEvent;
  compact: boolean;
  showDetails: boolean;
}) {
  return React.createElement(
    Box,
    { flexDirection: "column", marginY: 1, paddingLeft: compact ? 0 : 2 },
    React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"),
    React.createElement(Text, { wrap: "wrap" }, approval.title),
    approval.target ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target) : null,
    showDetails && approval.reason
      ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
      : null,
    React.createElement(Text, { color: "gray" }, "y allow · n deny · d details"),
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
          { bold: selected, color: selected ? "cyan" : "gray" },
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
  status,
  statusText,
}: StatusRenderProps & {
  frame: number;
  status: AgentStatus;
  statusText: string;
}): ReactNamespace.ReactElement | null {
  if (status !== "thinking" && status !== "cancelling" && status !== "starting") {
    return null;
  }
  const label = status === "starting" ? "Starting runtime" : statusText;
  return React.createElement(Text, { color: "cyan" }, `${TERMINAL_SPINNER_FRAMES[frame]} ${label}`);
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
}: RenderProps & {
  cursor: number;
  disabled: boolean;
  input: string;
  placeholder?: string;
  compact?: boolean;
}) {
  const characters = splitGraphemes(input);
  const safeCursor = Math.min(Math.max(cursor, 0), characters.length);
  const before = characters.slice(0, safeCursor).join("");
  const active = characters[safeCursor] || " ";
  const after = characters.slice(safeCursor + 1).join("");
  const activeCharacter = active === "\n" ? " " : active;
  const afterActive = active === "\n" ? `\n${after}` : after;
  return React.createElement(
    Box,
    { flexDirection: "row", marginTop: compact ? 0 : 1, alignItems: "flex-start" },
    React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "),
    input
      ? React.createElement(
          Text,
          { wrap: "wrap" },
          before,
          React.createElement(Text, { inverse: !disabled }, activeCharacter),
          afterActive,
        )
      : React.createElement(Text, { color: "gray" }, disabled ? "" : placeholder),
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
