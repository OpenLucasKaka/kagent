"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.shouldRenderInteractivePrompt = shouldRenderInteractivePrompt;
exports.shouldRenderSessionHeader = shouldRenderSessionHeader;
exports.scheduleTerminalCursorSync = scheduleTerminalCursorSync;
exports.KagentInkApp = KagentInkApp;
exports.isSessionCommandInput = isSessionCommandInput;
const approval_choice_1 = require("./approval-choice");
const app_state_1 = require("./app-state");
const commands_1 = require("./commands");
const editor_1 = require("./editor");
const runtime_client_1 = require("./runtime-client");
const provider_setup_1 = require("./provider-setup");
const terminal_input_1 = require("./terminal-input");
const transcript_1 = require("./transcript");
const ui_components_1 = require("./ui-components");
function shouldRenderInteractivePrompt(status, input = "") {
    return status === "idle" || status === "approval" || status === "error" || input !== "";
}
function shouldRenderSessionHeader(status, transcriptEntryCount) {
    return status !== "starting" && transcriptEntryCount === 0;
}
function scheduleTerminalCursorSync(control, scheduler) {
    let positioned = false;
    const token = scheduler.defer(() => {
        positioned = true;
        scheduler.write(control.position);
    });
    let active = true;
    return () => {
        if (!active) {
            return;
        }
        active = false;
        scheduler.cancel(token);
        if (positioned) {
            scheduler.write(control.restore);
        }
    };
}
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
    const [activitySeconds, setActivitySeconds] = React.useState(0);
    const [approvalChoice, setApprovalChoice] = React.useState("deny");
    const { transcript, status, statusText, approval, provider, setup, commandCatalog } = runtimeState;
    const commandMenu = (0, commands_1.updateCommandMenu)(commandCatalog, editor.value, selectedCommand);
    const terminalInputHandler = React.useRef(() => undefined);
    const activityStartedAt = React.useRef(Date.now());
    const submitInFlight = React.useRef(false);
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
        setApprovalChoice("deny");
        setShowApprovalDetails(false);
    }, [React, approval?.action_id]);
    React.useEffect(() => {
        if (status === "idle" || status === "error") {
            submitInFlight.current = false;
        }
    }, [React, status]);
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
    React.useEffect(() => {
        if (status !== "thinking" &&
            status !== "cancelling" &&
            status !== "starting" &&
            setup?.stage !== "saving") {
            setActivitySeconds(0);
            return undefined;
        }
        activityStartedAt.current = Date.now();
        setActivitySeconds(0);
        const timer = setInterval(() => {
            setActivitySeconds(Math.floor((Date.now() - activityStartedAt.current) / 1000));
        }, 250);
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
        if (key.ctrl && key.name === "o") {
            dispatchRuntime({
                type: "transcript_action",
                action: { type: "toggle_latest_result" },
            });
            return;
        }
        if (key.name === "pageup" || key.name === "pagedown") {
            const pagingLayout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
                approval: approval !== null,
                commandMenu: status === "idle" && commandMenu ? commandMenu : false,
                introVisible: transcript.entries.length === 0,
                prompt: editor.value,
                promptCursor: editor.cursor,
            });
            setTranscriptOffset((current) => (0, transcript_1.moveTranscriptViewport)(transcript.entries, {
                columns: pagingLayout.columns,
                rows: pagingLayout.rows,
                reservedRows: pagingLayout.reservedRows + (current > 0 ? 1 : 0),
            }, current, key.name === "pageup" ? "older" : "newer"));
            return;
        }
        if (status === "approval") {
            handleApprovalInput(value, key);
            return;
        }
        if (status === "cancelling") {
            return;
        }
        if (status === "thinking" && key.name === "escape") {
            runtime.cancel();
            dispatchRuntime({ type: "cancel_requested", label: "Stopping" });
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            if (key.shift || key.meta || key.sequence === "\n") {
                setEditor((current) => (0, editor_1.insertInput)(current, "\n"));
                return;
            }
            if (status === "thinking") {
                submitSteering();
            }
            else if (commandMenu) {
                const completion = (0, commands_1.commandCompletion)(commandMenu);
                if (completion.endsWith(" ")) {
                    setEditor((current) => ({
                        ...current,
                        value: completion,
                        cursor: (0, editor_1.splitGraphemes)(completion).length,
                        historyIndex: null,
                        draft: "",
                    }));
                    setSelectedCommand(null);
                }
                else {
                    submit(completion);
                }
            }
            else {
                submit();
            }
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
            moveEditorVerticalOrHistory(-1);
            return;
        }
        if (key.name === "down") {
            if (commandMenu) {
                setSelectedCommand((0, commands_1.moveCommandSelection)(commandMenu, 1).selectedCommand);
                return;
            }
            moveEditorVerticalOrHistory(1);
            return;
        }
        if (value && !key.ctrl && !key.meta) {
            setEditor((current) => (0, editor_1.insertInput)(current, value));
        }
    }
    function moveEditorVerticalOrHistory(direction) {
        const promptLayout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
            approval: approval !== null,
            commandMenu: false,
            introVisible: transcript.entries.length === 0,
            prompt: editor.value,
            promptCursor: editor.cursor,
        });
        if ((0, editor_1.editorVisualLineCount)(editor.value, promptLayout.promptColumns) > 1) {
            setEditor((current) => (0, editor_1.moveCursorVertical)(current, direction, promptLayout.promptColumns));
            return;
        }
        setEditor((current) => (0, editor_1.navigateHistory)(current, direction));
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
    function submit(value = "") {
        if (submitInFlight.current) {
            return;
        }
        const source = value
            ? {
                ...editor,
                value,
                cursor: (0, editor_1.splitGraphemes)(value).length,
            }
            : editor;
        const submission = (0, editor_1.submitInput)(source);
        if (!submission.value) {
            return;
        }
        const goal = submission.value;
        if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
            app.exit();
            return;
        }
        submitInFlight.current = true;
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
    function submitSteering() {
        const submission = (0, editor_1.submitInput)(editor);
        if (!submission.value) {
            return;
        }
        setEditor(submission.state);
        setSelectedCommand(null);
        try {
            runtime.steer(submission.value);
        }
        catch (error) {
            showError(errorMessage(error));
        }
    }
    function handleCommandEvent(event) {
        dispatchRuntime({ type: "runtime_event", channel: "command", event });
    }
    function handleApprovalInput(value, key) {
        if (!approval) {
            return;
        }
        const intent = (0, approval_choice_1.resolveApprovalInput)(approvalChoice, value, key.name);
        if (!intent) {
            return;
        }
        if (intent.type === "toggle_details") {
            setShowApprovalDetails((current) => !current);
            return;
        }
        if (intent.type === "select") {
            setApprovalChoice(intent.choice);
            return;
        }
        setShowApprovalDetails(false);
        dispatchRuntime({ type: "approval_response", approved: intent.approved });
        try {
            runtime.respondToApproval(approval.action_id, intent.approved);
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
        if (layout.tooNarrow) {
            return React.createElement(ui_components_1.NarrowTerminal, { React, Box, Text });
        }
        return React.createElement(Box, { flexDirection: "column", paddingX: layout.horizontalPadding }, React.createElement(ui_components_1.Header, {
            React,
            Box,
            Text,
            compact: layout.compact,
            provider: null,
            setup: true,
            workspace: process.cwd(),
        }), React.createElement(ui_components_1.ProviderSetupPanel, {
            React,
            Box,
            Text,
            frame,
            setup,
        }));
    }
    const sessionHeaderVisible = shouldRenderSessionHeader(status, transcript.entries.length);
    const layout = (0, ui_components_1.createTerminalLayout)(terminalSize.columns, terminalSize.rows, {
        approval: approval
            ? { ...approval, showDetails: showApprovalDetails }
            : false,
        commandMenu: status === "idle" && commandMenu ? commandMenu : false,
        introVisible: sessionHeaderVisible,
        prompt: editor.value,
        promptCursor: editor.cursor,
    });
    if (layout.tooNarrow) {
        return React.createElement(ui_components_1.NarrowTerminal, { React, Box, Text });
    }
    const visibleTranscript = (0, transcript_1.selectTranscriptViewport)(transcript.entries, {
        columns: layout.columns,
        rows: layout.rows,
        reservedRows: layout.reservedRows + (transcriptOffset > 0 ? 1 : 0),
    }, transcriptOffset);
    const promptDisabled = status === "cancelling" || status === "approval";
    const promptVisible = shouldRenderInteractivePrompt(status, editor.value);
    const promptCursorControl = (0, ui_components_1.createPromptTerminalCursorControl)({
        input: editor.value,
        cursor: editor.cursor,
        columns: layout.promptColumns,
        maxRows: layout.promptRowLimit,
        horizontalPadding: layout.horizontalPadding,
    });
    return React.createElement(Box, { flexDirection: "column", paddingX: layout.horizontalPadding }, sessionHeaderVisible
        ? React.createElement(ui_components_1.Header, {
            React,
            Box,
            Text,
            compact: layout.compact,
            provider,
            setup: false,
            workspace: process.cwd(),
        })
        : null, React.createElement(ui_components_1.TranscriptPosition, {
        React,
        Text,
        newerCount: transcriptOffset,
    }), React.createElement(ui_components_1.MessageList, { React, Box, Text, messages: visibleTranscript }), approval
        ? React.createElement(ui_components_1.ApprovalPanel, {
            React,
            Box,
            Text,
            approval,
            choice: approvalChoice,
            compact: layout.compact,
            showDetails: showApprovalDetails,
        })
        : null, React.createElement(ui_components_1.StatusLine, {
        React,
        Text,
        elapsedSeconds: activitySeconds,
        frame,
        status,
        statusText,
    }), commandMenu && status === "idle"
        ? React.createElement(ui_components_1.CommandPalette, {
            React,
            Box,
            Text,
            compact: layout.compact,
            limit: layout.commandLimit,
            menu: commandMenu,
        })
        : null, !promptVisible
        ? null
        : React.createElement(React.Fragment, null, React.createElement(ui_components_1.PromptLine, {
            React,
            Box,
            Text,
            cursor: editor.cursor,
            input: editor.value,
            disabled: promptDisabled,
            columns: layout.promptColumns,
            maxRows: layout.promptRowLimit,
            imeSafe: true,
        }), React.createElement(TerminalCursorSync, {
            React,
            control: promptDisabled ? null : promptCursorControl,
        })));
}
function TerminalCursorSync({ React, control, }) {
    React.useEffect(() => {
        if (!control || !process.stdout.isTTY) {
            return undefined;
        }
        return scheduleTerminalCursorSync(control, {
            write: (value) => process.stdout.write(value),
            defer: (callback) => setImmediate(callback),
            cancel: (token) => clearImmediate(token),
        });
    });
    return null;
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
