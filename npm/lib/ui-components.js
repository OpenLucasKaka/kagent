"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TERMINAL_SPINNER_FRAMES = void 0;
exports.shouldRenderPromptPlaceholder = shouldRenderPromptPlaceholder;
exports.shouldRenderInkPromptCursor = shouldRenderInkPromptCursor;
exports.createTerminalLayout = createTerminalLayout;
exports.estimateRuntimeActivityRows = estimateRuntimeActivityRows;
exports.NarrowTerminal = NarrowTerminal;
exports.createPromptViewport = createPromptViewport;
exports.createPromptTerminalCursorControl = createPromptTerminalCursorControl;
exports.Header = Header;
exports.ProviderSetupPanel = ProviderSetupPanel;
exports.MessageList = MessageList;
exports.RuntimeActivityWorkspace = RuntimeActivityWorkspace;
exports.TranscriptPosition = TranscriptPosition;
exports.ApprovalPanel = ApprovalPanel;
exports.CommandPalette = CommandPalette;
exports.StatusLine = StatusLine;
exports.PromptLine = PromptLine;
const editor_1 = require("./editor");
const provider_setup_1 = require("./provider-setup");
const terminal_text_1 = require("./terminal-text");
const terminal_width_1 = require("./terminal-width");
function shouldRenderPromptPlaceholder({ input, disabled, imeSafe, }) {
    return !input && !disabled && !imeSafe;
}
function shouldRenderInkPromptCursor({ input, disabled, imeSafe, }) {
    return Boolean(input) && !disabled && !imeSafe;
}
exports.TERMINAL_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
function createTerminalLayout(columns, rows, overlays) {
    const safeColumns = Math.max(1, columns || 80);
    const safeRows = Math.max(10, rows || 24);
    const tooNarrow = safeColumns < 20;
    const compact = safeColumns < 56;
    const horizontalPadding = compact ? 0 : 1;
    const defaultCommandLimit = compact ? 4 : 6;
    const headerRows = overlays.introVisible === false ? 0 : compact ? 2 : 3;
    const promptChromeRows = 1;
    const fixedBaseRows = headerRows + promptChromeRows;
    const approvalColumns = Math.max(4, safeColumns - horizontalPadding * 2 - (compact ? 0 : 2));
    const approvalRows = estimateApprovalRows(overlays.approval, approvalColumns);
    const commandColumns = Math.max(4, safeColumns - horizontalPadding * 2 - (compact ? 0 : 2));
    const commandExtraRows = estimateCommandExtraRows(overlays.commandMenu, compact, commandColumns);
    const activityColumns = Math.max(4, safeColumns - horizontalPadding * 2);
    const activityRows = overlays.activity
        ? estimateRuntimeActivityRows(overlays.activity, activityColumns, compact)
        : 0;
    const minimumActivityRows = overlays.activity ? 1 : 0;
    const commandCapacity = Math.max(1, safeRows - 1 - fixedBaseRows - 1 - commandExtraRows - approvalRows -
        minimumActivityRows);
    const commandLimit = overlays.commandMenu
        ? Math.min(defaultCommandLimit, commandCapacity)
        : defaultCommandLimit;
    const promptColumns = Math.max(4, safeColumns - horizontalPadding * 2 - 2);
    const visibleCommandRows = overlays.commandMenu && overlays.commandMenu !== true
        ? Math.min(commandLimit, overlays.commandMenu.options.length)
        : commandLimit;
    const commandRows = overlays.commandMenu
        ? visibleCommandRows + commandExtraRows
        : 0;
    const promptRowLimit = Math.max(1, Math.min(compact ? 4 : 6, safeRows - 1 - fixedBaseRows - approvalRows - commandRows -
        minimumActivityRows));
    const promptRows = overlays.prompt === undefined
        ? 1
        : (0, terminal_width_1.estimateTextRows)(createPromptViewport(overlays.prompt, overlays.promptCursor ?? (0, editor_1.splitGraphemes)(overlays.prompt).length, promptColumns, promptRowLimit).rendered, promptColumns);
    const baseRows = fixedBaseRows + promptRows;
    const activityRowLimit = overlays.activity
        ? Math.min(activityRows, Math.max(1, safeRows - 1 - baseRows - approvalRows - commandRows))
        : 0;
    return {
        columns: safeColumns,
        rows: safeRows,
        compact,
        tooNarrow,
        horizontalPadding,
        commandLimit,
        promptColumns,
        promptRowLimit,
        reservedRows: Math.min(safeRows - 1, baseRows + approvalRows + commandRows + activityRowLimit),
        ...(overlays.activity ? { activityRowLimit } : {}),
    };
}
function estimateRuntimeActivityRows(activity, columns, compact) {
    const safeColumns = Math.max(4, columns);
    const rows = (value) => Math.max(1, (0, terminal_width_1.estimateTextRows)(value, safeColumns));
    const phaseRows = rows(runtimeActivityPhaseLine(activity.phase, " · 99s", safeColumns));
    const detailRows = activity.detail ? rows(activity.detail) : 0;
    const outcomeRows = !compact && activity.latestOutcome
        ? rows(activity.latestOutcome)
        : 0;
    const footerRows = rows(`${activity.completedCount} completed · Ctrl+O details · Esc stop`);
    const timelineRows = activity.expanded
        ? activity.timeline.slice(-2).reduce((total, item) => total + rows([item.title, item.detail].filter(Boolean).join(" · ")), 0)
        : 0;
    return phaseRows + detailRows + outcomeRows + footerRows + timelineRows;
}
function NarrowTerminal({ React, Box, Text, }) {
    return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true, color: "cyan" }, "kagent"), React.createElement(Text, { color: "gray", wrap: "wrap" }, "widen terminal"));
}
function estimateApprovalRows(approval, columns) {
    if (!approval) {
        return 0;
    }
    if (approval === true) {
        return 8;
    }
    const rows = (value) => value ? (0, terminal_width_1.estimateTextRows)(value, columns) : 0;
    const detailRows = approval.showDetails
        ? (approval.details ?? []).reduce((total, detail) => total + rows(`  ${detail}`), 0)
        : 0;
    const detailMarginRows = approval.showDetails && approval.details?.length ? 1 : 0;
    const reasonRows = approval.showDetails ? rows(approval.reason) : 0;
    return (5 +
        rows(approval.title) +
        rows(approval.target) +
        rows("←→ select · enter confirm · d details") +
        detailMarginRows +
        detailRows +
        reasonRows);
}
function estimateCommandExtraRows(menu, compact, columns) {
    if (!menu) {
        return 0;
    }
    if (menu === true) {
        return compact ? 3 : 2;
    }
    const helpRows = (0, terminal_width_1.estimateTextRows)("↑↓ choose · tab complete · enter run", columns);
    const selected = menu.options[menu.selectedIndex];
    const descriptionRows = compact && selected
        ? (0, terminal_width_1.estimateTextRows)(`  ${selected.description}`, columns)
        : 0;
    return 1 + helpRows + descriptionRows;
}
function createPromptViewport(input, cursor, columns, maxRows) {
    const characters = (0, editor_1.splitGraphemes)(input);
    const safeCursor = Math.min(Math.max(cursor, 0), characters.length);
    const safeColumns = Math.max(4, columns);
    const safeRows = Math.max(1, maxRows);
    const preserveActiveNewline = safeRows > 1;
    let start = safeCursor;
    let end = Math.min(characters.length, safeCursor + 1);
    while (start > 0 &&
        promptViewportRows(characters, safeCursor, start - 1, end, safeColumns, preserveActiveNewline) <= safeRows) {
        start -= 1;
    }
    while (end < characters.length &&
        promptViewportRows(characters, safeCursor, start, end + 1, safeColumns, preserveActiveNewline) <= safeRows) {
        end += 1;
    }
    return promptViewportParts(characters, safeCursor, start, end, preserveActiveNewline);
}
function createPromptTerminalCursorControl({ input, cursor, columns, maxRows, horizontalPadding, }) {
    const viewport = createPromptViewport(input, cursor, columns, maxRows);
    const safeColumns = Math.max(4, columns);
    const cursorPosition = textEndPosition(viewport.before, safeColumns);
    const promptRows = (0, terminal_width_1.estimateTextRows)(viewport.rendered, safeColumns);
    const up = Math.max(1, promptRows - cursorPosition.row);
    const right = Math.max(0, horizontalPadding + 2 + cursorPosition.column);
    return {
        position: `${showTerminalCursor()}${moveCursorUp(up)}${moveCursorRight(right)}`,
        restore: `\r${moveCursorDown(up)}`,
    };
}
function promptViewportRows(characters, cursor, start, end, columns, preserveActiveNewline) {
    return (0, terminal_width_1.estimateTextRows)(promptViewportParts(characters, cursor, start, end, preserveActiveNewline).rendered, columns);
}
function promptViewportParts(characters, cursor, start, end, preserveActiveNewline) {
    const prefixClipped = start > 0;
    const suffixClipped = end < characters.length;
    const rawActive = characters[cursor] || " ";
    const active = rawActive === "\n" ? (preserveActiveNewline ? " " : "↵") : rawActive;
    const before = `${prefixClipped ? "…" : ""}${characters
        .slice(start, cursor)
        .join("")}`;
    const after = `${rawActive === "\n" && preserveActiveNewline ? "\n" : ""}${characters.slice(cursor + 1, end).join("")}${suffixClipped ? "…" : ""}`;
    return {
        before,
        active,
        after,
        rendered: `${before}${active}${after}`,
        prefixClipped,
        suffixClipped,
    };
}
function textEndPosition(text, columns) {
    let row = 0;
    let column = 0;
    for (const grapheme of (0, editor_1.splitGraphemes)(text)) {
        if (grapheme === "\n") {
            row += 1;
            column = 0;
            continue;
        }
        const width = Math.max(0, (0, terminal_text_1.terminalGraphemeWidth)(grapheme));
        if (column + width >= columns) {
            row += 1;
            column = 0;
        }
        else {
            column += width;
        }
    }
    return { row, column };
}
function showTerminalCursor() {
    return "\u001b[?25h";
}
function moveCursorUp(rows) {
    return rows > 0 ? `\u001b[${rows}A` : "";
}
function moveCursorDown(rows) {
    return rows > 0 ? `\u001b[${rows}B` : "";
}
function moveCursorRight(columns) {
    return columns > 0 ? `\u001b[${columns}C` : "";
}
function Header({ React, Box, Text, compact, provider, setup, workspace, }) {
    const providerLabel = provider?.configured
        ? `${(0, terminal_text_1.terminalSafeText)(provider.display_name)}${provider.model ? ` · ${(0, terminal_text_1.terminalSafeText)(provider.model)}` : ""}`
        : "";
    const safeWorkspace = (0, terminal_text_1.terminalSafeText)(workspace);
    if (compact) {
        const compactContext = setup ? "  setup" : ` · ${providerLabel || "local"}`;
        return React.createElement(Box, { flexDirection: "row", marginBottom: 1, flexShrink: 1 }, React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"), React.createElement(Text, { color: "gray", wrap: "truncate" }, compactContext));
    }
    const sessionLabel = [safeWorkspace, providerLabel].filter(Boolean).join(" · ") || "local session";
    return React.createElement(Box, { flexDirection: "column", marginBottom: 1 }, React.createElement(Box, { flexDirection: "row", flexShrink: 0 }, React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"), React.createElement(Text, { color: "gray" }, setup ? "  setup" : "")), React.createElement(Text, { color: "gray", wrap: "truncate" }, sessionLabel));
}
function ProviderSetupPanel({ React, Box, Text, frame, setup, }) {
    if (setup.stage === "provider") {
        return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, "Connect a model provider"), React.createElement(Box, { flexDirection: "column", marginTop: 1 }, ...setup.options.map((candidate, index) => React.createElement(Text, {
            key: candidate.provider,
            bold: setup.selectedIndex !== null && index === setup.selectedIndex,
            color: setup.selectedIndex !== null && index === setup.selectedIndex
                ? "cyan"
                : undefined,
        }, `${setup.selectedIndex !== null && index === setup.selectedIndex ? "›" : " "} ${candidate.label}`))), setup.error ? React.createElement(Text, { color: "red", wrap: "wrap" }, setup.error) : null, React.createElement(Text, { color: "gray" }, "↑↓ choose  enter continue  esc quit"));
    }
    const option = (0, provider_setup_1.selectedProvider)(setup);
    if (setup.stage === "saving") {
        return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, `Connect ${option.label}`), React.createElement(Text, { color: "cyan" }, `${exports.TERMINAL_SPINNER_FRAMES[frame]} Saving settings`));
    }
    const field = setupField(setup);
    const displayValue = setup.stage === "api_key" ? (0, provider_setup_1.maskSecret)(setup.editor.value) : setup.editor.value;
    return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, `Connect ${option.label}`), React.createElement(Text, { color: "gray", bold: true }, field.label), React.createElement(PromptLine, {
        React,
        Box,
        Text,
        cursor: setup.editor.cursor,
        input: displayValue,
        disabled: false,
        placeholder: field.placeholder,
        compact: true,
    }), setup.error ? React.createElement(Text, { color: "red", wrap: "wrap" }, setup.error) : null, React.createElement(Text, { color: "gray" }, "enter continue  esc back"));
}
function MessageList({ React, Box, Text, messages, }) {
    return React.createElement(Box, { flexDirection: "column" }, ...messages.map((message) => {
        const marker = message.role === "user" ? "›" : message.role === "assistant" ? "•" : message.role === "command" ? "·" : "!";
        const color = message.role === "user" ? "cyan" : message.role === "system" ? "red" : message.role === "command" ? "gray" : undefined;
        return React.createElement(Box, { key: message.id, flexDirection: "row", marginBottom: 1 }, React.createElement(Text, { color, bold: message.role === "user" }, `${marker} `), React.createElement(Box, { flexDirection: "column", flexGrow: 1, flexShrink: 1 }, message.title ? React.createElement(Text, { bold: true, color }, message.title) : null, message.detail
            ? React.createElement(Text, { color: "gray", wrap: "wrap" }, message.detail)
            : null, message.text
            ? React.createElement(Text, { color, wrap: "wrap" }, message.text)
            : null, message.expanded && message.content
            ? React.createElement(Text, { color: "gray", wrap: "wrap" }, message.content)
            : null));
    }));
}
function RuntimeActivityWorkspace({ React, Box, Text, activity, compact, frame, elapsedSeconds, maxRows, columns = 80, }) {
    const safeColumns = Math.max(4, columns);
    const elapsed = elapsedSeconds > 0 ? ` · ${elapsedSeconds}s` : "";
    const phase = runtimeActivityPhaseLine(activity.phase, elapsed, safeColumns, exports.TERMINAL_SPINNER_FRAMES[frame]);
    const footer = `${activity.completedCount} completed · Ctrl+O details · Esc stop`;
    const rows = (value) => Math.max(1, (0, terminal_width_1.estimateTextRows)(value, safeColumns));
    const phaseRows = rows(phase);
    const footerRows = rows(footer);
    const footerVisible = phaseRows + footerRows <= maxRows;
    let contentRows = Math.max(0, maxRows - phaseRows - (footerVisible ? footerRows : 0));
    const detailRows = activity.detail ? rows(activity.detail) : 0;
    const canShowDetail = detailRows > 0 && detailRows <= contentRows;
    if (canShowDetail) {
        contentRows -= detailRows;
    }
    const outcomeRows = activity.latestOutcome ? rows(activity.latestOutcome) : 0;
    const canShowOutcome = !compact && outcomeRows > 0 && outcomeRows <= contentRows;
    if (canShowOutcome) {
        contentRows -= outcomeRows;
    }
    const timeline = activity.expanded
        ? activity.timeline.slice(-2).reduceRight((visible, item) => {
            const itemRows = rows([item.title, item.detail].filter(Boolean).join(" · "));
            return itemRows <= contentRows
                ? (contentRows -= itemRows, [item, ...visible])
                : visible;
        }, [])
        : [];
    return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { color: "cyan", wrap: "wrap" }, phase), canShowDetail
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, (0, terminal_text_1.terminalSafeText)(activity.detail))
        : null, canShowOutcome
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, (0, terminal_text_1.terminalSafeText)(activity.latestOutcome))
        : null, footerVisible
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, footer)
        : null, ...timeline.map((item, index) => React.createElement(Text, { key: `${index}-${item.title}`, color: "gray", wrap: "wrap" }, (0, terminal_text_1.terminalSafeText)([item.title, item.detail].filter(Boolean).join(" · ")))));
}
function runtimeActivityPhaseLine(phase, elapsed, columns, spinner = "⠋") {
    const value = `${spinner} ${(0, terminal_text_1.terminalSafeText)(phase)}${elapsed}`;
    if ((0, terminal_width_1.estimateTextRows)(value, columns) <= 1) {
        return value;
    }
    const ellipsis = "…";
    const limit = Math.max(1, columns - (0, terminal_text_1.terminalGraphemeWidth)(ellipsis));
    let width = 0;
    const visible = [];
    for (const grapheme of (0, editor_1.splitGraphemes)(value)) {
        const graphemeWidth = (0, terminal_text_1.terminalGraphemeWidth)(grapheme);
        if (width + graphemeWidth > limit) {
            break;
        }
        width += graphemeWidth;
        visible.push(grapheme);
    }
    return `${visible.join("")}${ellipsis}`;
}
function TranscriptPosition({ React, Text, newerCount, }) {
    if (newerCount <= 0) {
        return null;
    }
    return React.createElement(Text, { color: "gray" }, `History · ${newerCount} newer`);
}
function ApprovalPanel({ React, Box, Text, approval, choice, compact, showDetails, }) {
    return React.createElement(Box, { flexDirection: "column", marginY: 1, paddingLeft: compact ? 0 : 2 }, React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"), React.createElement(Text, { wrap: "wrap" }, approval.title), approval.target ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target) : null, showDetails && approval.details?.length
        ? React.createElement(Box, { flexDirection: "column", marginTop: 1 }, ...approval.details.map((detail, index) => React.createElement(Text, { key: `${index}-${detail}`, color: "cyan", wrap: "wrap" }, `  ${detail}`)))
        : null, showDetails && approval.reason
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
        : null, React.createElement(Box, { flexDirection: "row", marginTop: 1 }, React.createElement(Text, { bold: choice === "allow", color: choice === "allow" ? "cyan" : "gray" }, `${choice === "allow" ? "›" : " "} Allow once`), React.createElement(Text, {
        bold: choice === "deny",
        color: choice === "deny" ? "yellow" : "gray",
    }, `${compact ? "  " : "    "}${choice === "deny" ? "›" : " "} Deny`)), React.createElement(Text, { color: "gray" }, "←→ select · enter confirm · d details"));
}
function CommandPalette({ React, Box, Text, compact, limit, menu, }) {
    const visibleStart = Math.min(Math.max(menu.selectedIndex - limit + 1, 0), Math.max(menu.options.length - limit, 0));
    const visibleOptions = menu.options.slice(visibleStart, visibleStart + limit);
    return React.createElement(Box, { flexDirection: "column", paddingLeft: compact ? 0 : 2, marginTop: 1 }, ...visibleOptions.map((option, index) => {
        const selected = visibleStart + index === menu.selectedIndex;
        return React.createElement(Box, { key: option.command, flexDirection: compact ? "column" : "row" }, React.createElement(Text, {
            bold: selected,
            color: selected ? "cyan" : "gray",
            wrap: "truncate",
        }, `${selected ? "›" : " "} ${option.command}`), compact
            ? selected
                ? React.createElement(Text, { color: "gray", wrap: "wrap" }, `  ${option.description}`)
                : null
            : React.createElement(Text, { color: "gray", wrap: "truncate" }, `  ${option.description}`));
    }), React.createElement(Text, { color: "gray" }, "↑↓ choose · tab complete · enter run"));
}
function StatusLine({ React, Text, frame, elapsedSeconds, status, statusText, }) {
    if (status !== "thinking" && status !== "cancelling" && status !== "starting") {
        return null;
    }
    const label = status === "starting" ? "Starting runtime" : statusText;
    const elapsed = elapsedSeconds > 0 ? ` · ${elapsedSeconds}s` : "";
    return React.createElement(Text, { color: "cyan" }, `${exports.TERMINAL_SPINNER_FRAMES[frame]} ${label}${elapsed}`);
}
function PromptLine({ React, Box, Text, cursor, disabled, input, placeholder = "Ask kagent", compact = false, columns = 80, maxRows = 6, imeSafe = false, }) {
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
    return React.createElement(Box, { flexDirection: "row", marginTop: compact ? 0 : 1, alignItems: "flex-start" }, React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "), input
        ? React.createElement(Text, { wrap: "wrap" }, promptContent)
        : React.createElement(Text, { color: "gray" }, renderPlaceholder ? placeholder : ""));
}
function setupField(setup) {
    if (setup.stage === "base_url") {
        return { label: "Base URL", placeholder: "https://api.example.com/v1" };
    }
    if (setup.stage === "model") {
        return { label: "Model", placeholder: "model-id" };
    }
    const required = (0, provider_setup_1.selectedProvider)(setup).api_key_required;
    return {
        label: required ? "API key" : "API key (optional)",
        placeholder: required ? "Paste API key" : "Leave empty for local providers",
    };
}
