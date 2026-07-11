"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.KagentInkApp = KagentInkApp;
exports.isSessionCommandInput = isSessionCommandInput;
const app_state_1 = require("./app-state");
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
    const [runtimeState, setRuntimeState] = React.useState(app_state_1.createAppRuntimeState);
    const [transcriptOffset, setTranscriptOffset] = React.useState(0);
    const [frame, setFrame] = React.useState(0);
    const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
    const [selectedCommand, setSelectedCommand] = React.useState(null);
    const [terminalSize, setTerminalSize] = React.useState(() => currentTerminalSize());
    const { transcript, status, statusText, approval, provider, setup, commandCatalog } = runtimeState;
    const commandMenu = (0, commands_1.updateCommandMenu)(commandCatalog, editor.value, selectedCommand);
    const terminalInputHandler = React.useRef(() => undefined);
    terminalInputHandler.current = handleTerminalInput;
    function dispatchRuntime(action) {
        setRuntimeState((current) => (0, app_state_1.appRuntimeReducer)(current, action));
    }
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
        if (setup?.stage !== "saving") {
            return;
        }
        runtime.configureProvider((0, provider_setup_1.providerConfiguration)(setup), handleProviderEvent);
    }, [React, runtime, setup]);
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
                    dispatchRuntime({ type: "setup_action", action: { type: "back" } });
                    return;
                }
                app.exit();
                return;
            }
            if (status === "thinking" || status === "cancelling") {
                runtime.cancel();
                dispatchRuntime({ type: "cancel_requested", label: "Stopping" });
                return;
            }
            if (status === "approval" && approval) {
                dispatchRuntime({ type: "approval_response", approved: false });
                try {
                    runtime.respondToApproval(approval.action_id, false);
                }
                catch (error) {
                    showError(errorMessage(error));
                }
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
        dispatchRuntime({ type: "runtime_event", channel: "lifecycle", event });
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
                dispatchRuntime({ type: "setup_action", action: { type: "back" } });
            }
            return;
        }
        if (setup.stage === "provider") {
            if (key.name === "up") {
                dispatchRuntime({
                    type: "setup_action",
                    action: { type: "select", offset: -1 },
                });
            }
            else if (key.name === "down") {
                dispatchRuntime({
                    type: "setup_action",
                    action: { type: "select", offset: 1 },
                });
            }
            else if (key.name === "return" || key.name === "enter") {
                dispatchRuntime({ type: "setup_action", action: { type: "next" } });
            }
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            dispatchRuntime({ type: "setup_action", action: { type: "next" } });
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
        setRuntimeState((current) => {
            if (!current.setup || !(0, provider_setup_1.isInputStage)(current.setup.stage)) {
                return current;
            }
            return (0, app_state_1.appRuntimeReducer)(current, {
                type: "setup_action",
                action: { type: "edit", editor: update(current.setup.editor) },
            });
        });
    }
    function handleProviderEvent(event) {
        dispatchRuntime({ type: "runtime_event", channel: "provider", event });
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
        setEditor(submission.state);
        setSelectedCommand(null);
        const command = isSessionCommandInput(goal);
        dispatchRuntime({ type: "submit", text: goal, command });
        if (command) {
            runtime.command(goal, handleCommandEvent);
            return;
        }
        runtime.run(goal, handleRuntimeEvent);
    }
    function handleCommandEvent(event) {
        dispatchRuntime({ type: "runtime_event", channel: "command", event });
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
        setShowApprovalDetails(false);
        dispatchRuntime({ type: "approval_response", approved: answer === "y" });
        try {
            runtime.respondToApproval(approval.action_id, answer === "y");
        }
        catch (error) {
            showError(errorMessage(error));
        }
    }
    function handleRuntimeEvent(event) {
        dispatchRuntime({ type: "runtime_event", channel: "run", event });
    }
    function showError(message) {
        dispatchRuntime({ type: "error", message });
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
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function isSessionCommandInput(value) {
    return !value.includes("\n") && value.trimStart().startsWith("/");
}
