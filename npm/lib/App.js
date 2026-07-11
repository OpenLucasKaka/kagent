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
const ui_components_1 = require("./ui-components");
function KagentInkApp({ React, Ink, runtimeSessionFactory = runtime_client_1.createRuntimeSessionClient, }) {
    const { Box, Text } = Ink;
    const app = Ink.useApp();
    const { internal_eventEmitter: inputEvents, setRawMode } = Ink.useStdin();
    const [runtime] = React.useState(() => runtimeSessionFactory());
    const [editor, setEditor] = React.useState(editor_1.createEditorState);
    const [transcript, setTranscript] = React.useState(transcript_1.createTranscriptState);
    const [transcriptOffset, setTranscriptOffset] = React.useState(0);
    const [status, setStatus] = React.useState("starting");
    const [statusText, setStatusText] = React.useState("");
    const [frame, setFrame] = React.useState(0);
    const [approval, setApproval] = React.useState(null);
    const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
    const [provider, setProvider] = React.useState(null);
    const [setup, setSetup] = React.useState(null);
    const [commandCatalog, setCommandCatalog] = React.useState([]);
    const [selectedCommand, setSelectedCommand] = React.useState(null);
    const [terminalSize, setTerminalSize] = React.useState(() => currentTerminalSize());
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
        const handleResize = () => setTerminalSize(currentTerminalSize());
        process.stdout.on("resize", handleResize);
        return () => {
            process.stdout.removeListener("resize", handleResize);
        };
    }, [React]);
    React.useEffect(() => {
        setTranscriptOffset(0);
    }, [React, transcript.nextId]);
    React.useEffect(() => {
        if (status !== "thinking" &&
            status !== "cancelling" &&
            status !== "starting" &&
            setup?.stage !== "saving") {
            return undefined;
        }
        const timer = setInterval(() => {
            setFrame((current) => (current + 1) % ui_components_1.TERMINAL_SPINNER_FRAMES.length);
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
            if (status === "thinking" || status === "cancelling") {
                runtime.cancel();
                setStatus("cancelling");
                setStatusText("Stopping");
                return;
            }
            if (status === "approval" && approval) {
                runtime.respondToApproval(approval.action_id, false);
                setApproval(null);
                setStatus("thinking");
                setStatusText("Cancelling");
                return;
            }
            app.exit();
            return;
        }
        if (setup) {
            handleSetupInput(value, key);
            return;
        }
        if (key.name === "pageup" || key.name === "pagedown") {
            const pagingLayout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
                approval: approval !== null,
                commandMenu: commandMenu !== null && status === "idle",
                prompt: editor.value,
            });
            setTranscriptOffset((current) => (0, transcript_1.moveTranscriptViewport)(transcript.entries, {
                columns: pagingLayout.columns,
                rows: pagingLayout.rows,
                reservedRows: pagingLayout.reservedRows + (current > 0 ? 1 : 0),
            }, current, key.name === "pageup" ? "older" : "newer"));
            return;
        }
        if (status === "approval") {
            handleApprovalInput(value);
            return;
        }
        if (status === "thinking" || status === "cancelling") {
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            if (key.shift || key.meta || key.sequence === "\n") {
                setEditor((current) => (0, editor_1.insertInput)(current, "\n"));
                return;
            }
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
            updateSetupEditor((current) => (0, editor_1.insertInput)(current, value.replace(/\n/g, " ")));
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
        if (event.type === "run_cancel_requested") {
            setStatus("cancelling");
            setStatusText("Stopping");
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
        const layout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
            approval: false,
            commandMenu: false,
        });
        return React.createElement(Box, { flexDirection: "column", paddingX: layout.horizontalPadding }, React.createElement(ui_components_1.Header, {
            React,
            Box,
            Text,
            compact: layout.compact,
            provider: null,
            setup: true,
        }), React.createElement(ui_components_1.ProviderSetupPanel, {
            React,
            Box,
            Text,
            frame,
            setup,
        }));
    }
    const layout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
        approval: approval !== null,
        commandMenu: commandMenu !== null && status === "idle",
        prompt: editor.value,
    });
    const visibleTranscript = (0, transcript_1.selectTranscriptViewport)(transcript.entries, {
        columns: layout.columns,
        rows: layout.rows,
        reservedRows: layout.reservedRows + (transcriptOffset > 0 ? 1 : 0),
    }, transcriptOffset);
    return React.createElement(Box, { flexDirection: "column", paddingX: layout.horizontalPadding }, React.createElement(ui_components_1.Header, {
        React,
        Box,
        Text,
        compact: layout.compact,
        provider,
        setup: false,
    }), React.createElement(ui_components_1.TranscriptPosition, {
        React,
        Text,
        newerCount: transcriptOffset,
    }), React.createElement(ui_components_1.MessageList, { React, Box, Text, messages: visibleTranscript }), approval
        ? React.createElement(ui_components_1.ApprovalPanel, {
            React,
            Box,
            Text,
            approval,
            compact: layout.compact,
            showDetails: showApprovalDetails,
        })
        : null, React.createElement(ui_components_1.StatusLine, { React, Text, frame, status, statusText }), commandMenu && status === "idle"
        ? React.createElement(ui_components_1.CommandPalette, {
            React,
            Box,
            Text,
            compact: layout.compact,
            limit: layout.commandLimit,
            menu: commandMenu,
        })
        : null, status === "starting"
        ? null
        : React.createElement(ui_components_1.PromptLine, {
            React,
            Box,
            Text,
            cursor: editor.cursor,
            input: editor.value,
            disabled: status === "thinking" || status === "cancelling" || status === "approval",
        }));
}
function currentTerminalSize() {
    return {
        columns: process.stdout.columns || 80,
        rows: process.stdout.rows || 24,
    };
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
    return !value.includes("\n") && value.trimStart().startsWith("/");
}
