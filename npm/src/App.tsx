import type ReactNamespace from "react";

import {
  commandCompletion,
  moveCommandSelection,
  updateCommandMenu,
} from "./commands";
import {
  createEditorState,
  deleteAtCursor,
  deleteBeforeCursor,
  insertInput,
  moveCursor,
  moveCursorToEnd,
  moveCursorToStart,
  navigateHistory,
  splitGraphemes,
  submitInput,
  type EditorBuffer,
  type EditorState,
} from "./editor";
import {
  createRuntimeSessionClient,
  type RuntimeClientEvent,
  type RuntimeSessionClient,
} from "./runtime-client";
import {
  createProviderSetupState,
  isInputStage,
  providerConfiguration,
  providerSetupReducer,
  type ProviderSetupState,
} from "./provider-setup";
import type {
  ApprovalRequiredEvent,
  ProviderSnapshot,
  RuntimeReadyEvent,
  SessionCommandOption,
} from "./protocol";
import {
  createTerminalInputBridge,
  type TerminalInputHandler,
  type TerminalKey,
} from "./terminal-input";
import {
  createTranscriptState,
  moveTranscriptViewport,
  progressTranscriptAction,
  selectTranscriptViewport,
  transcriptReducer,
} from "./transcript";
import {
  ApprovalPanel,
  CommandPalette,
  Header,
  MessageList,
  PromptLine,
  ProviderSetupPanel,
  StatusLine,
  TERMINAL_SPINNER_FRAMES,
  TranscriptPosition,
  createTerminalLayout,
  type AgentStatus,
} from "./ui-components";

type InkApi = {
  Box: ReactNamespace.ElementType;
  Text: ReactNamespace.ElementType;
  useApp: () => { exit: () => void };
  useStdin: () => {
    setRawMode: (value: boolean) => void;
    internal_eventEmitter: {
      on: (event: "input", listener: (input: string | Buffer) => void) => void;
      removeListener: (event: "input", listener: (input: string | Buffer) => void) => void;
    };
  };
};

type AppProps = {
  React: typeof ReactNamespace;
  Ink: InkApi;
  runtimeSessionFactory?: typeof createRuntimeSessionClient;
};

export function KagentInkApp({
  React,
  Ink,
  runtimeSessionFactory = createRuntimeSessionClient,
}: AppProps): ReactNamespace.ReactElement {
  const { Box, Text } = Ink;
  const app = Ink.useApp();
  const { internal_eventEmitter: inputEvents, setRawMode } = Ink.useStdin();
  const [runtime] = React.useState<RuntimeSessionClient>(() => runtimeSessionFactory());
  const [editor, setEditor] = React.useState<EditorState>(createEditorState);
  const [transcript, setTranscript] = React.useState(createTranscriptState);
  const [transcriptOffset, setTranscriptOffset] = React.useState(0);
  const [status, setStatus] = React.useState<AgentStatus>("starting");
  const [statusText, setStatusText] = React.useState("");
  const [frame, setFrame] = React.useState(0);
  const [approval, setApproval] = React.useState<ApprovalRequiredEvent | null>(null);
  const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
  const [provider, setProvider] = React.useState<ProviderSnapshot | null>(null);
  const [setup, setSetup] = React.useState<ProviderSetupState | null>(null);
  const [commandCatalog, setCommandCatalog] = React.useState<SessionCommandOption[]>([]);
  const [selectedCommand, setSelectedCommand] = React.useState<string | null>(null);
  const [terminalSize, setTerminalSize] = React.useState(() => currentTerminalSize());
  const commandMenu = updateCommandMenu(commandCatalog, editor.value, selectedCommand);
  const terminalInputHandler = React.useRef<TerminalInputHandler>(() => undefined);
  terminalInputHandler.current = handleTerminalInput;

  React.useEffect(() => {
    const bridge = createTerminalInputBridge((input, key) => {
      terminalInputHandler.current(input, key);
    });
    const handleRawInput = (input: string | Buffer): void => bridge.write(input);
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
    const handleResize = (): void => setTerminalSize(currentTerminalSize());
    process.stdout.on("resize", handleResize);
    return () => {
      process.stdout.removeListener("resize", handleResize);
    };
  }, [React]);

  React.useEffect(() => {
    setTranscriptOffset(0);
  }, [React, transcript.nextId]);

  React.useEffect(() => {
    if (
      status !== "thinking" &&
      status !== "cancelling" &&
      status !== "starting" &&
      setup?.stage !== "saving"
    ) {
      return undefined;
    }
    const timer = setInterval(() => {
      setFrame((current) => (current + 1) % TERMINAL_SPINNER_FRAMES.length);
    }, 90);
    return () => clearInterval(timer);
  }, [React, setup?.stage, status]);

  function handleTerminalInput(value: string, key: TerminalKey): void {
    if (key.ctrl && key.name === "c") {
      if (setup) {
        if (setup.stage === "saving") {
          runtime.cancel();
          setSetup((current) =>
            current ? providerSetupReducer(current, { type: "back" }) : current,
          );
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
      const pagingLayout = createTerminalLayout(
        terminalSize.columns,
        terminalSize.rows,
        {
          approval: approval !== null,
          commandMenu: commandMenu !== null && status === "idle",
          prompt: editor.value,
        },
      );
      setTranscriptOffset((current) =>
        moveTranscriptViewport(
          transcript.entries,
          {
            columns: pagingLayout.columns,
            rows: pagingLayout.rows,
            reservedRows: pagingLayout.reservedRows + (current > 0 ? 1 : 0),
          },
          current,
          key.name === "pageup" ? "older" : "newer",
        ),
      );
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
        setEditor((current) => insertInput(current, "\n"));
        return;
      }
      submit();
      return;
    }
    if (key.name === "tab" && commandMenu) {
      const completion = commandCompletion(commandMenu);
      setEditor((current) => ({
        ...current,
        value: completion,
        cursor: splitGraphemes(completion).length,
        historyIndex: null,
        draft: "",
      }));
      setSelectedCommand(null);
      return;
    }
    if (key.name === "backspace") {
      setEditor(deleteBeforeCursor);
      return;
    }
    if (key.name === "delete") {
      setEditor(deleteAtCursor);
      return;
    }
    if (key.name === "left") {
      setEditor((current) => moveCursor(current, -1));
      return;
    }
    if (key.name === "right") {
      setEditor((current) => moveCursor(current, 1));
      return;
    }
    if (key.name === "home" || (key.ctrl && key.name === "a")) {
      setEditor(moveCursorToStart);
      return;
    }
    if (key.name === "end" || (key.ctrl && key.name === "e")) {
      setEditor(moveCursorToEnd);
      return;
    }
    if (key.name === "up") {
      if (commandMenu) {
        setSelectedCommand(moveCommandSelection(commandMenu, -1).selectedCommand);
        return;
      }
      setEditor((current) => navigateHistory(current, -1));
      return;
    }
    if (key.name === "down") {
      if (commandMenu) {
        setSelectedCommand(moveCommandSelection(commandMenu, 1).selectedCommand);
        return;
      }
      setEditor((current) => navigateHistory(current, 1));
      return;
    }
    if (value && !key.ctrl && !key.meta) {
      setEditor((current) => insertInput(current, value));
    }
  }

  function handleLifecycleEvent(event: RuntimeClientEvent): void {
    if (event.type === "runtime_ready") {
      applyRuntimeReady(event);
      return;
    }
    if (event.type === "runtime_unavailable" || event.type === "client_failed") {
      showError(event.message);
    }
  }

  function applyRuntimeReady(event: RuntimeReadyEvent): void {
    setProvider(event.provider);
    setCommandCatalog(event.session_commands || []);
    if (event.provider.configured) {
      setSetup(null);
      setStatus("idle");
      return;
    }
    try {
      setSetup(createProviderSetupState(event.provider_options));
      setStatus("idle");
    } catch (error) {
      showError(errorMessage(error));
    }
  }

  function handleSetupInput(
    value: string,
    key: TerminalKey,
  ): void {
    if (!setup || setup.stage === "saving") {
      return;
    }
    if (key.name === "escape") {
      if (setup.stage === "provider") {
        app.exit();
      } else {
        setSetup(providerSetupReducer(setup, { type: "back" }));
      }
      return;
    }
    if (setup.stage === "provider") {
      if (key.name === "up") {
        setSetup(providerSetupReducer(setup, { type: "select", offset: -1 }));
      } else if (key.name === "down") {
        setSetup(providerSetupReducer(setup, { type: "select", offset: 1 }));
      } else if (key.name === "return" || key.name === "enter") {
        setSetup(providerSetupReducer(setup, { type: "next" }));
      }
      return;
    }
    if (key.name === "return" || key.name === "enter") {
      const next = providerSetupReducer(setup, { type: "next" });
      setSetup(next);
      if (next.stage === "saving") {
        runtime.configureProvider(providerConfiguration(next), handleProviderEvent);
      }
      return;
    }
    if (key.name === "backspace") {
      updateSetupEditor(deleteBeforeCursor);
      return;
    }
    if (key.name === "delete") {
      updateSetupEditor(deleteAtCursor);
      return;
    }
    if (key.name === "left") {
      updateSetupEditor((current) => moveCursor(current, -1));
      return;
    }
    if (key.name === "right") {
      updateSetupEditor((current) => moveCursor(current, 1));
      return;
    }
    if (key.name === "home" || (key.ctrl && key.name === "a")) {
      updateSetupEditor(moveCursorToStart);
      return;
    }
    if (key.name === "end" || (key.ctrl && key.name === "e")) {
      updateSetupEditor(moveCursorToEnd);
      return;
    }
    if (value && !key.ctrl && !key.meta) {
      updateSetupEditor((current) => insertInput(current, value.replace(/\n/g, " ")));
    }
  }

  function updateSetupEditor(update: (current: EditorBuffer) => EditorBuffer): void {
    setSetup((current) => {
      if (!current || !isInputStage(current.stage)) {
        return current;
      }
      return providerSetupReducer(current, {
        type: "edit",
        editor: update(current.editor),
      });
    });
  }

  function handleProviderEvent(event: RuntimeClientEvent): void {
    if (event.type === "provider_configured") {
      setProvider(event.provider);
      setSetup(null);
      setStatus("idle");
      return;
    }
    if (event.type === "provider_configuration_failed" || event.type === "client_failed") {
      setSetup((current) =>
        current
          ? providerSetupReducer(current, {
              type: "failure",
              message: event.message,
              field: event.type === "provider_configuration_failed" ? event.field : undefined,
            })
          : current,
      );
    }
  }

  function submit(): void {
    const submission = submitInput(editor);
    if (!submission.value) {
      return;
    }
    const goal = submission.value;
    if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
      app.exit();
      return;
    }
    setTranscript((current) =>
      transcriptReducer(current, { type: "user_submitted", text: goal }),
    );
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

  function handleCommandEvent(event: RuntimeClientEvent): void {
    if (event.type === "session_command_completed") {
      setStatus("idle");
      setStatusText("");
      setTranscript((current) =>
        transcriptReducer(current, {
          type: "command_completed",
          title: event.title,
          text: event.message,
          clear: event.clear_messages,
        }),
      );
      return;
    }
    if (event.type === "session_command_failed" || event.type === "client_failed") {
      showError(event.message);
    }
  }

  function handleApprovalInput(value: string): void {
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
    } catch (error) {
      setApproval(null);
      showError(errorMessage(error));
    }
  }

  function handleRuntimeEvent(event: RuntimeClientEvent): void {
    if (event.type === "run_started") {
      setStatus("thinking");
      setStatusText("Thinking");
      return;
    }
    if (event.type === "run_progress") {
      setStatusText(progressLabel(event.event));
      const action = progressTranscriptAction(event.event);
      if (action) {
        setTranscript((current) => transcriptReducer(current, action));
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
      setTranscript((current) =>
        transcriptReducer(current, {
          type: "assistant_completed",
          text: event.answer || fallback,
          outcome: event.status === "cancelled" ? "cancelled" : "complete",
        }),
      );
      return;
    }
    if (event.type === "run_failed" || event.type === "client_failed") {
      setApproval(null);
      showError(event.message);
      return;
    }
  }

  function showError(message: string): void {
    setStatus("error");
    setStatusText("");
    setTranscript((current) =>
      transcriptReducer(current, { type: "error", text: message }),
    );
  }

  if (setup) {
    const layout = createTerminalLayout(terminalSize.columns, terminalSize.rows, {
      approval: false,
      commandMenu: false,
    });
    return React.createElement(
      Box,
      { flexDirection: "column", paddingX: layout.horizontalPadding },
      React.createElement(Header, {
        React,
        Box,
        Text,
        compact: layout.compact,
        provider: null,
        setup: true,
      }),
      React.createElement(ProviderSetupPanel, {
        React,
        Box,
        Text,
        frame,
        setup,
      }),
    );
  }

  const layout = createTerminalLayout(terminalSize.columns, terminalSize.rows, {
    approval: approval !== null,
    commandMenu: commandMenu !== null && status === "idle",
    prompt: editor.value,
  });
  const visibleTranscript = selectTranscriptViewport(
    transcript.entries,
    {
      columns: layout.columns,
      rows: layout.rows,
      reservedRows: layout.reservedRows + (transcriptOffset > 0 ? 1 : 0),
    },
    transcriptOffset,
  );

  return React.createElement(
    Box,
    { flexDirection: "column", paddingX: layout.horizontalPadding },
    React.createElement(Header, {
      React,
      Box,
      Text,
      compact: layout.compact,
      provider,
      setup: false,
    }),
    React.createElement(TranscriptPosition, {
      React,
      Text,
      newerCount: transcriptOffset,
    }),
    React.createElement(MessageList, { React, Box, Text, messages: visibleTranscript }),
    approval
      ? React.createElement(ApprovalPanel, {
          React,
          Box,
          Text,
          approval,
          compact: layout.compact,
          showDetails: showApprovalDetails,
        })
      : null,
    React.createElement(StatusLine, { React, Text, frame, status, statusText }),
    commandMenu && status === "idle"
      ? React.createElement(CommandPalette, {
          React,
          Box,
          Text,
          compact: layout.compact,
          limit: layout.commandLimit,
          menu: commandMenu,
        })
      : null,
    status === "starting"
      ? null
      : React.createElement(PromptLine, {
          React,
          Box,
          Text,
          cursor: editor.cursor,
          input: editor.value,
          disabled: status === "thinking" || status === "cancelling" || status === "approval",
        }),
  );
}

function currentTerminalSize(): { columns: number; rows: number } {
  return {
    columns: process.stdout.columns || 80,
    rows: process.stdout.rows || 24,
  };
}

function progressLabel(event: Record<string, unknown>): string {
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function isSessionCommandInput(value: string): boolean {
  return !value.includes("\n") && value.trimStart().startsWith("/");
}
