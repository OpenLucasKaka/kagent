"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.KagentInkApp = KagentInkApp;
exports.deleteBeforeCursor = deleteBeforeCursor;
exports.applyInput = applyInput;
exports.moveCursor = moveCursor;
exports.splitGraphemes = splitGraphemes;
const runtime_client_1 = require("./runtime-client");
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: "grapheme" });
function KagentInkApp({ React, Ink, runtimeSessionFactory = runtime_client_1.createRuntimeSessionClient, }) {
    const { Box, Text } = Ink;
    const app = Ink.useApp();
    const [runtime] = React.useState(() => runtimeSessionFactory());
    const [editor, setEditor] = React.useState({ value: "", cursor: 0 });
    const [messages, setMessages] = React.useState([]);
    const [status, setStatus] = React.useState("idle");
    const [statusText, setStatusText] = React.useState("");
    const [frame, setFrame] = React.useState(0);
    const [approval, setApproval] = React.useState(null);
    const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
    React.useEffect(() => () => runtime.close(), [React, runtime]);
    React.useEffect(() => {
        if (status !== "thinking") {
            return undefined;
        }
        const timer = setInterval(() => {
            setFrame((current) => (current + 1) % FRAMES.length);
        }, 90);
        return () => clearInterval(timer);
    }, [React, status]);
    Ink.useInput((value, key) => {
        if (key.ctrl && value === "c") {
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
        if (status === "approval") {
            handleApprovalInput(value);
            return;
        }
        if (status === "thinking") {
            return;
        }
        if (key.return) {
            submit();
            return;
        }
        if (key.backspace || key.delete || value === "\b" || value === "\x7f") {
            setEditor(deleteBeforeCursor);
            return;
        }
        if (key.leftArrow) {
            setEditor((current) => moveCursor(current, -1));
            return;
        }
        if (key.rightArrow) {
            setEditor((current) => moveCursor(current, 1));
            return;
        }
        if (value && !key.ctrl && !key.meta) {
            setEditor((current) => applyInput(current, value));
        }
    });
    function submit() {
        const goal = editor.value.trim();
        if (!goal) {
            return;
        }
        if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
            app.exit();
            return;
        }
        setMessages((current) => current.concat({ role: "user", text: goal }));
        setEditor({ value: "", cursor: 0 });
        setStatus("thinking");
        setStatusText("Thinking");
        runtime.run(goal, handleRuntimeEvent);
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
            setMessages((current) => current.concat({ role: "assistant", text: event.answer || fallback }));
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
        setMessages((current) => current.concat({ role: "system", text: message }));
    }
    return React.createElement(Box, { flexDirection: "column", paddingX: 1 }, React.createElement(Header, { React, Box, Text }), React.createElement(MessageList, { React, Box, Text, messages }), approval
        ? React.createElement(ApprovalPanel, {
            React,
            Box,
            Text,
            approval,
            showDetails: showApprovalDetails,
        })
        : null, React.createElement(StatusLine, { React, Text, frame, status, statusText }), React.createElement(PromptLine, {
        React,
        Box,
        Text,
        cursor: editor.cursor,
        input: editor.value,
        disabled: status === "thinking" || status === "approval",
    }));
}
function Header({ React, Box, Text }) {
    return React.createElement(Box, { marginBottom: 1 }, React.createElement(Text, { bold: true, color: "cyan" }, "kagent"), React.createElement(Text, { color: "gray" }, "  agent runtime"));
}
function MessageList({ React, Box, Text, messages }) {
    const recent = messages.slice(-10);
    return React.createElement(Box, { flexDirection: "column" }, ...recent.map((message, index) => {
        const marker = message.role === "user" ? "›" : message.role === "assistant" ? "•" : "!";
        const color = message.role === "user" ? "cyan" : message.role === "assistant" ? undefined : "red";
        return React.createElement(Box, { key: `${message.role}-${index}`, flexDirection: "row", marginBottom: 1 }, React.createElement(Text, { color, bold: message.role === "user" }, `${marker} `), React.createElement(Text, { color, wrap: "wrap" }, message.text));
    }));
}
function ApprovalPanel({ React, Box, Text, approval, showDetails, }) {
    return React.createElement(Box, { flexDirection: "column", marginY: 1, paddingLeft: 2 }, React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"), React.createElement(Text, null, approval.title), approval.target
        ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target)
        : null, showDetails && approval.reason
        ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
        : null, React.createElement(Text, { color: "gray" }, "y allow   n deny   d details"));
}
function StatusLine({ React, Text, frame, status, statusText, }) {
    if (status !== "thinking") {
        return React.createElement(Text, null, "");
    }
    return React.createElement(Text, { color: "cyan" }, `${FRAMES[frame]} ${statusText}`);
}
function PromptLine({ React, Box, Text, cursor, disabled, input, }) {
    const characters = splitGraphemes(input);
    const safeCursor = Math.min(Math.max(cursor, 0), characters.length);
    const before = characters.slice(0, safeCursor).join("");
    const active = characters[safeCursor] || " ";
    const after = characters.slice(safeCursor + 1).join("");
    return React.createElement(Box, { flexDirection: "row", marginTop: 1, alignItems: "flex-start" }, React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "), input
        ? React.createElement(Text, { wrap: "wrap" }, before, React.createElement(Text, { inverse: !disabled }, active), after)
        : React.createElement(Text, { color: "gray" }, disabled ? "" : "Ask kagent"));
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
function deleteBeforeCursor(state) {
    const characters = splitGraphemes(state.value);
    const cursor = Math.min(Math.max(state.cursor, 0), characters.length);
    if (cursor <= 0) {
        return state;
    }
    characters.splice(cursor - 1, 1);
    return {
        value: characters.join(""),
        cursor: cursor - 1,
    };
}
function applyInput(state, rawInput) {
    const characters = splitGraphemes(state.value);
    let cursor = Math.min(Math.max(state.cursor, 0), characters.length);
    for (const character of splitGraphemes(rawInput)) {
        if (character === "\b" || character === "\x7f") {
            if (cursor > 0) {
                characters.splice(cursor - 1, 1);
                cursor -= 1;
            }
            continue;
        }
        if ((character.codePointAt(0) || 0) < 32) {
            continue;
        }
        characters.splice(cursor, 0, character);
        cursor += 1;
    }
    return { value: characters.join(""), cursor };
}
function moveCursor(state, offset) {
    const length = splitGraphemes(state.value).length;
    return {
        ...state,
        cursor: Math.min(Math.max(state.cursor + offset, 0), length),
    };
}
function splitGraphemes(value) {
    return Array.from(GRAPHEME_SEGMENTER.segment(value), ({ segment }) => segment);
}
