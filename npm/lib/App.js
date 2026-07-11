"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.KagentInkApp = KagentInkApp;
exports.isSessionCommandInput = isSessionCommandInput;
const commands_1 = require("./commands");
const editor_1 = require("./editor");
const runtime_client_1 = require("./runtime-client");
const provider_setup_1 = require("./provider-setup");
const terminal_input_1 = require("./terminal-input");
const transcript_1 = require("./transcript");
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
function KagentInkApp({ React, Ink, runtimeSessionFactory = runtime_client_1.createRuntimeSessionClient, }) {
    const { Box, Text } = Ink;
    const app = Ink.useApp();
    const { internal_eventEmitter: inputEvents, setRawMode } = Ink.useStdin();
    const [runtime] = React.useState(() => runtimeSessionFactory());
    const [editor, setEditor] = React.useState(editor_1.createEditorState);
    const [transcript, setTranscript] = React.useState(transcript_1.createTranscriptState);
    const [status, setStatus] = React.useState("starting");
    const [statusText, setStatusText] = React.useState("");
    const [frame, setFrame] = React.useState(0);
    const [approval, setApproval] = React.useState(null);
    const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
    const [provider, setProvider] = React.useState(null);
    const [setup, setSetup] = React.useState(null);
    const [commandCatalog, setCommandCatalog] = React.useState([]);
    const [selectedCommand, setSelectedCommand] = React.useState(null);
    const commandMenu = (0, commands_1.updateCommandMenu)(commandCatalog, editor.value, selectedCommand);
    const terminalInputHandler = React.useRef(() => undefined);
    terminalInputHandler.current = handleTerminalInput;
    React.useEffect(() => {
        const bridge = (0, terminal_input_1.createTerminalInputBridge)((input, key) => {
            terminalInputHandler.current(input, key);
        });
        const handleRawInput = (input) => bridge.write(input);
        inputEvents.on("input", handleRawInput);
        setRawMode(true);
        return () => {
            inputEvents.removeListener("input", handleRawInput);
            bridge.close();
            setRawMode(false);
        };
    }, [React, inputEvents, setRawMode]);
    React.useEffect(() => {
        const unsubscribe = runtime.subscribe(handleLifecycleEvent);
        return () => {
            unsubscribe();
            runtime.close();
        };
    }, [React, runtime]);
    React.useEffect(() => {
        if (status !== "thinking" && status !== "starting" && setup?.stage !== "saving") {
            return undefined;
        }
        const timer = setInterval(() => {
            setFrame((current) => (current + 1) % FRAMES.length);
        }, 90);
        return () => clearInterval(timer);
    }, [React, setup?.stage, status]);
    function handleTerminalInput(value, key) {
        if (key.ctrl && key.name === "c") {
            if (setup) {
                if (setup.stage === "saving") {
                    runtime.cancel();
                    setSetup((current) => current ? (0, provider_setup_1.providerSetupReducer)(current, { type: "back" }) : current);
                    return;
                }
                app.exit();
                return;
            }
            if (status === "thinking" || status === "approval") {
                runtime.cancel();
                setApproval(null);
                setStatus("idle");
                setStatusText("");
                return;
            }
            app.exit();
            return;
        }
        if (setup) {
            handleSetupInput(value, key);
            return;
        }
        if (status === "approval") {
            handleApprovalInput(value);
            return;
        }
        if (status === "thinking") {
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            submit();
            return;
        }
        if (key.name === "tab" && commandMenu) {
            const completion = (0, commands_1.commandCompletion)(commandMenu);
            setEditor((current) => ({
                ...current,
                value: completion,
                cursor: (0, editor_1.splitGraphemes)(completion).length,
                historyIndex: null,
                draft: "",
            }));
            setSelectedCommand(null);
            return;
        }
        if (key.name === "backspace") {
            setEditor(editor_1.deleteBeforeCursor);
            return;
        }
        if (key.name === "delete") {
            setEditor(editor_1.deleteAtCursor);
            return;
        }
        if (key.name === "left") {
            setEditor((current) => (0, editor_1.moveCursor)(current, -1));
            return;
        }
        if (key.name === "right") {
            setEditor((current) => (0, editor_1.moveCursor)(current, 1));
            return;
        }
        if (key.name === "home" || (key.ctrl && key.name === "a")) {
            setEditor(editor_1.moveCursorToStart);
            return;
        }
        if (key.name === "end" || (key.ctrl && key.name === "e")) {
            setEditor(editor_1.moveCursorToEnd);
            return;
        }
        if (key.name === "up") {
            if (commandMenu) {
                setSelectedCommand((0, commands_1.moveCommandSelection)(commandMenu, -1).selectedCommand);
                return;
            }
            setEditor((current) => (0, editor_1.navigateHistory)(current, -1));
            return;
        }
        if (key.name === "down") {
            if (commandMenu) {
                setSelectedCommand((0, commands_1.moveCommandSelection)(commandMenu, 1).selectedCommand);
                return;
            }
            setEditor((current) => (0, editor_1.navigateHistory)(current, 1));
            return;
        }
        if (value && !key.ctrl && !key.meta) {
            setEditor((current) => (0, editor_1.insertInput)(current, value));
        }
    }
    function handleLifecycleEvent(event) {
        if (event.type === "runtime_ready") {
            applyRuntimeReady(event);
            return;
        }
        if (event.type === "runtime_unavailable" || event.type === "client_failed") {
            showError(event.message);
        }
    }
    function applyRuntimeReady(event) {
        setProvider(event.provider);
        setCommandCatalog(event.session_commands || []);
        if (event.provider.configured) {
            setSetup(null);
            setStatus("idle");
            return;
        }
        try {
            setSetup((0, provider_setup_1.createProviderSetupState)(event.provider_options));
            setStatus("idle");
        }
        catch (error) {
            showError(errorMessage(error));
        }
    }
    function handleSetupInput(value, key) {
        if (!setup || setup.stage === "saving") {
            return;
        }
        if (key.name === "escape") {
            if (setup.stage === "provider") {
                app.exit();
            }
            else {
                setSetup((0, provider_setup_1.providerSetupReducer)(setup, { type: "back" }));
            }
            return;
        }
        if (setup.stage === "provider") {
            if (key.name === "up") {
                setSetup((0, provider_setup_1.providerSetupReducer)(setup, { type: "select", offset: -1 }));
            }
            else if (key.name === "down") {
                setSetup((0, provider_setup_1.providerSetupReducer)(setup, { type: "select", offset: 1 }));
            }
            else if (key.name === "return" || key.name === "enter") {
                setSetup((0, provider_setup_1.providerSetupReducer)(setup, { type: "next" }));
            }
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            const next = (0, provider_setup_1.providerSetupReducer)(setup, { type: "next" });
            setSetup(next);
            if (next.stage === "saving") {
                runtime.configureProvider((0, provider_setup_1.providerConfiguration)(next), handleProviderEvent);
            }
            return;
        }
        if (key.name === "backspace") {
            updateSetupEditor(editor_1.deleteBeforeCursor);
            return;
        }
        if (key.name === "delete") {
            updateSetupEditor(editor_1.deleteAtCursor);
            return;
        }
        if (key.name === "left") {
            updateSetupEditor((current) => (0, editor_1.moveCursor)(current, -1));
            return;
        }
        if (key.name === "right") {
            updateSetupEditor((current) => (0, editor_1.moveCursor)(current, 1));
            return;
        }
        if (key.name === "home" || (key.ctrl && key.name === "a")) {
            updateSetupEditor(editor_1.moveCursorToStart);
            return;
        }
        if (key.name === "end" || (key.ctrl && key.name === "e")) {
            updateSetupEditor(editor_1.moveCursorToEnd);
            return;
        }
        if (value && !key.ctrl && !key.meta) {
            updateSetupEditor((current) => (0, editor_1.insertInput)(current, value));
        }
    }
    function updateSetupEditor(update) {
        setSetup((current) => {
            if (!current || !(0, provider_setup_1.isInputStage)(current.stage)) {
                return current;
            }
            return (0, provider_setup_1.providerSetupReducer)(current, {
                type: "edit",
                editor: update(current.editor),
            });
        });
    }
    function handleProviderEvent(event) {
        if (event.type === "provider_configured") {
            setProvider(event.provider);
            setSetup(null);
            setStatus("idle");
            return;
        }
        if (event.type === "provider_configuration_failed" || event.type === "client_failed") {
            setSetup((current) => current
                ? (0, provider_setup_1.providerSetupReducer)(current, {
                    type: "failure",
                    message: event.message,
                    field: event.type === "provider_configuration_failed" ? event.field : undefined,
                })
                : current);
        }
    }
    function submit() {
        const submission = (0, editor_1.submitInput)(editor);
        if (!submission.value) {
            return;
        }
        const goal = submission.value;
        if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
            app.exit();
            return;
        }
        setTranscript((current) => (0, transcript_1.transcriptReducer)(current, { type: "user_submitted", text: goal }));
        setEditor(submission.state);
        setSelectedCommand(null);
        setStatus("thinking");
        if (isSessionCommandInput(goal)) {
            setStatusText("Running command");
            runtime.command(goal, handleCommandEvent);
            return;
        }
        setStatusText("Thinking");
        runtime.run(goal, handleRuntimeEvent);
    }
    function handleCommandEvent(event) {
        if (event.type === "session_command_completed") {
            setStatus("idle");
            setStatusText("");
            setTranscript((current) => (0, transcript_1.transcriptReducer)(current, {
                type: "command_completed",
                title: event.title,
                text: event.message,
                clear: event.clear_messages,
            }));
            return;
        }
        if (event.type === "session_command_failed" || event.type === "client_failed") {
            showError(event.message);
        }
    }
    function handleApprovalInput(value) {
        if (!approval) {
            return;
        }
        const answer = value.toLowerCase();
        if (answer === "d") {
            setShowApprovalDetails((current) => !current);
            return;
        }
        if (answer !== "y" && answer !== "n") {
            return;
        }
        setStatus("thinking");
        setStatusText(answer === "y" ? "Continuing" : "Cancelling");
        setShowApprovalDetails(false);
        try {
            runtime.respondToApproval(approval.action_id, answer === "y");
            setApproval(null);
        }
        catch (error) {
            setApproval(null);
            showError(errorMessage(error));
        }
    }
    function handleRuntimeEvent(event) {
        if (event.type === "run_started") {
            setStatus("thinking");
            setStatusText("Thinking");
            return;
        }
        if (event.type === "run_progress") {
            setStatusText(progressLabel(event.event));
            const action = (0, transcript_1.progressTranscriptAction)(event.event);
            if (action) {
                setTranscript((current) => (0, transcript_1.transcriptReducer)(current, action));
            }
            return;
        }
        if (event.type === "approval_required") {
            setApproval(event);
            setStatus("approval");
            setStatusText("");
            return;
        }
        if (event.type === "run_completed") {
            setApproval(null);
            setStatus("idle");
            setStatusText("");
            const fallback = event.status === "cancelled" ? "Action cancelled." : "Done.";
            setTranscript((current) => (0, transcript_1.transcriptReducer)(current, {
                type: "assistant_completed",
                text: event.answer || fallback,
                outcome: event.status === "cancelled" ? "cancelled" : "complete",
            }));
            return;
        }
        if (event.type === "run_failed" || event.type === "client_failed") {
            setApproval(null);
            showError(event.message);
            return;
        }
    }
    function showError(message) {
        setStatus("error");
        setStatusText("");
        setTranscript((current) => (0, transcript_1.transcriptReducer)(current, { type: "error", text: message }));
    }
    if (setup) {
        return React.createElement(Box, { flexDirection: "column", paddingX: 1 }, React.createElement(Header, { React, Box, Text, provider: null, setup: true }), React.createElement(ProviderSetupPanel, {
            React,
            Box,
            Text,
            frame,
            setup,
        }));
    }
    const visibleTranscript = (0, transcript_1.selectTranscriptViewport)(transcript.entries, {
        columns: process.stdout.columns || 80,
        rows: process.stdout.rows || 24,
        reservedRows: 6 + (approval ? 6 : 0) + (commandMenu ? 7 : 0),
    });
    return React.createElement(Box, { flexDirection: "column", paddingX: 1 }, React.createElement(Header, { React, Box, Text, provider, setup: false }), React.createElement(MessageList, { React, Box, Text, messages: visibleTranscript }), approval
        ? React.createElement(ApprovalPanel, {
            React,
            Box,
            Text,
            approval,
            showDetails: showApprovalDetails,
        })
        : null, React.createElement(StatusLine, { React, Text, frame, status, statusText }), commandMenu && status === "idle"
        ? React.createElement(CommandPalette, { React, Box, Text, menu: commandMenu })
        : null, status === "starting"
        ? null
        : React.createElement(PromptLine, {
            React,
            Box,
            Text,
            cursor: editor.cursor,
            input: editor.value,
            disabled: status === "thinking" || status === "approval",
        }));
}
function Header({ React, Box, Text, provider, setup, }) {
    return React.createElement(Box, { flexDirection: "column", marginBottom: 1 }, React.createElement(Box, { flexDirection: "row" }, React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"), React.createElement(Text, { color: "gray" }, setup ? "  setup" : "  agent")), provider?.configured
        ? React.createElement(Text, { color: "gray" }, `${provider.display_name}${provider.model ? ` · ${provider.model}` : ""}`)
        : null);
}
function ProviderSetupPanel({ React, Box, Text, frame, setup, }) {
    const option = (0, provider_setup_1.selectedProvider)(setup);
    if (setup.stage === "provider") {
        return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, "Connect a model provider"), React.createElement(Text, { color: "gray" }, "Choose where kagent should think."), React.createElement(Box, { flexDirection: "column", marginTop: 1 }, ...setup.options.map((candidate, index) => React.createElement(Text, {
            key: candidate.provider,
            bold: index === setup.selectedIndex,
            color: index === setup.selectedIndex ? "cyan" : undefined,
        }, `${index === setup.selectedIndex ? "›" : " "} ${candidate.label}`))), React.createElement(Text, { color: "gray" }, "↑↓ choose  enter continue  esc quit"));
    }
    if (setup.stage === "saving") {
        return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, `Connect ${option.label}`), React.createElement(Text, { color: "cyan" }, `${FRAMES[frame]} Saving settings`));
    }
    const field = setupField(setup);
    const displayValue = setup.stage === "api_key" ? (0, provider_setup_1.maskSecret)(setup.editor.value) : setup.editor.value;
    return React.createElement(Box, { flexDirection: "column" }, React.createElement(Text, { bold: true }, `Connect ${option.label}`), React.createElement(Text, { color: "gray" }, field.hint), React.createElement(Text, { color: "gray", bold: true }, field.label), React.createElement(PromptLine, {
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
function setupField(setup) {
    if (setup.stage === "base_url") {
        return {
            label: "Base URL",
            hint: "OpenAI-compatible API endpoint",
            placeholder: "https://api.example.com/v1",
        };
    }
    if (setup.stage === "model") {
        return {
            label: "Model",
            hint: "Exact model ID exposed by the provider",
            placeholder: "model-id",
        };
    }
    const required = (0, provider_setup_1.selectedProvider)(setup).api_key_required;
    return {
        label: required ? "API key" : "API key (optional)",
        hint: "Stored locally with owner-only permissions",
        placeholder: required ? "Paste API key" : "Leave empty for local providers",
    };
}
function MessageList({ React, Box, Text, messages, }) {
    return React.createElement(Box, { flexDirection: "column" }, ...messages.map((message) => {
        const marker = message.role === "user"
            ? "›"
            : message.role === "assistant"
                ? "•"
                : message.role === "command"
                    ? "·"
                    : "!";
        const color = message.role === "user"
            ? "cyan"
            : message.role === "system"
                ? "red"
                : message.role === "command"
                    ? "gray"
                    : undefined;
        return React.createElement(Box, { key: message.id, flexDirection: "row", marginBottom: 1 }, React.createElement(Text, { color, bold: message.role === "user" }, `${marker} `), React.createElement(Box, { flexDirection: "column", flexGrow: 1 }, message.title
            ? React.createElement(Text, { bold: true, color }, message.title)
            : null, React.createElement(Text, { color, wrap: "wrap" }, message.text)));
    }));
}
function ApprovalPanel({ React, Box, Text, approval, showDetails, }) {
    return React.createElement(Box, { flexDirection: "column", marginY: 1, paddingLeft: 2 }, React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"), React.createElement(Text, null, approval.title), approval.target
        ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target)
        : null, showDetails && approval.reason
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
        : null, React.createElement(Text, { color: "gray" }, "y allow   n deny   d details"));
}
function CommandPalette({ React, Box, Text, menu, }) {
    const visibleStart = Math.min(Math.max(menu.selectedIndex - 5, 0), Math.max(menu.options.length - 6, 0));
    const visibleOptions = menu.options.slice(visibleStart, visibleStart + 6);
    return React.createElement(Box, { flexDirection: "column", paddingLeft: 2, marginTop: 1 }, ...visibleOptions.map((option, index) => {
        const selected = visibleStart + index === menu.selectedIndex;
        return React.createElement(Box, { key: option.command, flexDirection: "row" }, React.createElement(Text, {
            bold: selected,
            color: selected ? "cyan" : "gray",
        }, `${selected ? "›" : " "} ${option.command}`), React.createElement(Text, { color: "gray" }, `  ${option.description}`));
    }), React.createElement(Text, { color: "gray" }, "↑↓ choose  tab complete  enter run"));
}
function StatusLine({ React, Text, frame, status, statusText, }) {
    if (status !== "thinking" && status !== "starting") {
        return React.createElement(Text, null, "");
    }
    const label = status === "starting" ? "Starting runtime" : statusText;
    return React.createElement(Text, { color: "cyan" }, `${FRAMES[frame]} ${label}`);
}
function PromptLine({ React, Box, Text, cursor, disabled, input, placeholder = "Ask kagent", compact = false, }) {
    const characters = (0, editor_1.splitGraphemes)(input);
    const safeCursor = Math.min(Math.max(cursor, 0), characters.length);
    const before = characters.slice(0, safeCursor).join("");
    const active = characters[safeCursor] || " ";
    const after = characters.slice(safeCursor + 1).join("");
    return React.createElement(Box, { flexDirection: "row", marginTop: compact ? 0 : 1, alignItems: "flex-start" }, React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "), input
        ? React.createElement(Text, { wrap: "wrap" }, before, React.createElement(Text, { inverse: !disabled }, active), after)
        : React.createElement(Text, { color: "gray" }, disabled ? "" : placeholder));
}
function progressLabel(event) {
    const type = String(event.type || "");
    if (type === "planner_started") {
        return "Thinking";
    }
    if (type === "plan_ready" || type === "tool_started" || type === "tool_completed") {
        return "Working";
    }
    if (type.endsWith("failed")) {
        return "Retrying";
    }
    return "Working";
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function isSessionCommandInput(value) {
    return value.trimStart().startsWith("/");
}
