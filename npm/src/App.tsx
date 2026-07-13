import type ReactNamespace from "react";

import {
  resolveApprovalInput,
  type ApprovalChoice,
} from "./approval-choice";
import {
  appRuntimeReducer,
  createAppRuntimeState,
  type AppRuntimeAction,
} from "./app-state";
import {
  commandCompletion,
  moveCommandSelection,
  updateCommandMenu,
} from "./commands";
import {
  createEditorState,
  deleteAtCursor,
  deleteBeforeCursor,
  editorVisualLineCount,
  insertInput,
  moveCursor,
  moveCursorToEnd,
  moveCursorToStart,
  moveCursorVertical,
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
  isInputStage,
  providerConfiguration,
} from "./provider-setup";
import {
  createTerminalInputBridge,
  type TerminalInputHandler,
  type TerminalKey,
} from "./terminal-input";
import {
  moveTranscriptViewport,
  selectTranscriptViewport,
} from "./transcript";
import {
  ApprovalPanel,
  CommandPalette,
  Header,
  MessageList,
  NarrowTerminal,
  PromptLine,
  ProviderSetupPanel,
  StatusLine,
  TERMINAL_SPINNER_FRAMES,
  TranscriptPosition,
  createPromptTerminalCursorControl,
  createTerminalLayout,
  type AgentStatus,
  type PromptTerminalCursorControl,
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

export function shouldRenderInteractivePrompt(
  status: AgentStatus,
  input = "",
): boolean {
  return status === "idle" || status === "approval" || status === "error" || input !== "";
}

export function shouldRenderSessionHeader(
  status: AgentStatus,
  transcriptEntryCount: number,
): boolean {
  return status !== "starting" && transcriptEntryCount === 0;
}

export type TerminalCursorScheduler<Token = NodeJS.Immediate> = {
  write: (value: string) => void;
  defer: (callback: () => void) => Token;
  cancel: (token: Token) => void;
};

export function scheduleTerminalCursorSync<Token>(
  control: PromptTerminalCursorControl,
  scheduler: TerminalCursorScheduler<Token>,
): () => void {
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
  const [runtimeState, setRuntimeState] = React.useState(createAppRuntimeState);
  const [transcriptOffset, setTranscriptOffset] = React.useState(0);
  const [frame, setFrame] = React.useState(0);
  const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
  const [selectedCommand, setSelectedCommand] = React.useState<string | null>(null);
  const [terminalSize, setTerminalSize] = React.useState(() => currentTerminalSize());
  const [activitySeconds, setActivitySeconds] = React.useState(0);
  const [approvalChoice, setApprovalChoice] = React.useState<ApprovalChoice>("deny");
  const { transcript, status, statusText, approval, provider, setup, commandCatalog } =
    runtimeState;
  const commandMenu = updateCommandMenu(commandCatalog, editor.value, selectedCommand);
  const terminalInputHandler = React.useRef<TerminalInputHandler>(() => undefined);
  const activityStartedAt = React.useRef(Date.now());
  const submitInFlight = React.useRef(false);
  terminalInputHandler.current = handleTerminalInput;

  function dispatchRuntime(action: AppRuntimeAction): void {
    setRuntimeState((current) => appRuntimeReducer(current, action));
  }

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
    if (setup?.stage !== "saving") {
      return;
    }
    runtime.configureProvider(providerConfiguration(setup), handleProviderEvent);
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

  React.useEffect(() => {
    if (
      status !== "thinking" &&
      status !== "cancelling" &&
      status !== "starting" &&
      setup?.stage !== "saving"
    ) {
      setActivitySeconds(0);
      return undefined;
    }
    activityStartedAt.current = Date.now();
    setActivitySeconds(0);
    const timer = setInterval(() => {
      setActivitySeconds(
        Math.floor((Date.now() - activityStartedAt.current) / 1000),
      );
    }, 250);
    return () => clearInterval(timer);
  }, [React, setup?.stage, status]);

  function handleTerminalInput(value: string, key: TerminalKey): void {
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
        } catch (error) {
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
      const pagingLayout = createTerminalLayout(
        terminalSize.columns,
        terminalSize.rows,
        {
          approval: approval !== null,
          commandMenu: status === "idle" && commandMenu ? commandMenu : false,
          introVisible: transcript.entries.length === 0,
          prompt: editor.value,
          promptCursor: editor.cursor,
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
        setEditor((current) => insertInput(current, "\n"));
        return;
      }
      if (status === "thinking") {
        submitSteering();
      } else if (commandMenu) {
        const completion = commandCompletion(commandMenu);
        if (completion.endsWith(" ")) {
          setEditor((current) => ({
            ...current,
            value: completion,
            cursor: splitGraphemes(completion).length,
            historyIndex: null,
            draft: "",
          }));
          setSelectedCommand(null);
        } else {
          submit(completion);
        }
      } else {
        submit();
      }
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
      moveEditorVerticalOrHistory(-1);
      return;
    }
    if (key.name === "down") {
      if (commandMenu) {
        setSelectedCommand(moveCommandSelection(commandMenu, 1).selectedCommand);
        return;
      }
      moveEditorVerticalOrHistory(1);
      return;
    }
    if (value && !key.ctrl && !key.meta) {
      setEditor((current) => insertInput(current, value));
    }
  }

  function moveEditorVerticalOrHistory(direction: -1 | 1): void {
    const promptLayout = createTerminalLayout(
      terminalSize.columns,
      terminalSize.rows,
      {
        approval: approval !== null,
        commandMenu: false,
        introVisible: transcript.entries.length === 0,
        prompt: editor.value,
        promptCursor: editor.cursor,
      },
    );
    if (editorVisualLineCount(editor.value, promptLayout.promptColumns) > 1) {
      setEditor((current) =>
        moveCursorVertical(current, direction, promptLayout.promptColumns),
      );
      return;
    }
    setEditor((current) => navigateHistory(current, direction));
  }

  function handleLifecycleEvent(event: RuntimeClientEvent): void {
    dispatchRuntime({ type: "runtime_event", channel: "lifecycle", event });
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
      } else if (key.name === "down") {
        dispatchRuntime({
          type: "setup_action",
          action: { type: "select", offset: 1 },
        });
      } else if (key.name === "return" || key.name === "enter") {
        dispatchRuntime({ type: "setup_action", action: { type: "next" } });
      }
      return;
    }
    if (key.name === "return" || key.name === "enter") {
      dispatchRuntime({ type: "setup_action", action: { type: "next" } });
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
    setRuntimeState((current) => {
      if (!current.setup || !isInputStage(current.setup.stage)) {
        return current;
      }
      return appRuntimeReducer(current, {
        type: "setup_action",
        action: { type: "edit", editor: update(current.setup.editor) },
      });
    });
  }

  function handleProviderEvent(event: RuntimeClientEvent): void {
    dispatchRuntime({ type: "runtime_event", channel: "provider", event });
  }

  function submit(value = ""): void {
    if (submitInFlight.current) {
      return;
    }
    const source = value
      ? {
          ...editor,
          value,
          cursor: splitGraphemes(value).length,
        }
      : editor;
    const submission = submitInput(source);
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

  function submitSteering(): void {
    const submission = submitInput(editor);
    if (!submission.value) {
      return;
    }
    setEditor(submission.state);
    setSelectedCommand(null);
    try {
      runtime.steer(submission.value);
    } catch (error) {
      showError(errorMessage(error));
    }
  }

  function handleCommandEvent(event: RuntimeClientEvent): void {
    dispatchRuntime({ type: "runtime_event", channel: "command", event });
  }

  function handleApprovalInput(value: string, key: TerminalKey): void {
    if (!approval) {
      return;
    }
    const intent = resolveApprovalInput(approvalChoice, value, key.name);
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
    } catch (error) {
      showError(errorMessage(error));
    }
  }

  function handleRuntimeEvent(event: RuntimeClientEvent): void {
    dispatchRuntime({ type: "runtime_event", channel: "run", event });
  }

  function showError(message: string): void {
    dispatchRuntime({ type: "error", message });
  }

  if (setup) {
    const layout = createTerminalLayout(terminalSize.columns, terminalSize.rows, {
      approval: false,
      commandMenu: false,
    });
    if (layout.tooNarrow) {
      return React.createElement(NarrowTerminal, { React, Box, Text });
    }
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
        workspace: process.cwd(),
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

  const sessionHeaderVisible = shouldRenderSessionHeader(
    status,
    transcript.entries.length,
  );
  const layout = createTerminalLayout(terminalSize.columns, terminalSize.rows, {
    approval: approval
      ? { ...approval, showDetails: showApprovalDetails }
      : false,
    commandMenu: status === "idle" && commandMenu ? commandMenu : false,
    introVisible: sessionHeaderVisible,
    prompt: editor.value,
    promptCursor: editor.cursor,
  });
  if (layout.tooNarrow) {
    return React.createElement(NarrowTerminal, { React, Box, Text });
  }
  const visibleTranscript = selectTranscriptViewport(
    transcript.entries,
    {
      columns: layout.columns,
      rows: layout.rows,
      reservedRows: layout.reservedRows + (transcriptOffset > 0 ? 1 : 0),
    },
    transcriptOffset,
  );
  const promptDisabled = status === "cancelling" || status === "approval";
  const promptVisible = shouldRenderInteractivePrompt(status, editor.value);
  const promptCursorControl = createPromptTerminalCursorControl({
    input: editor.value,
    cursor: editor.cursor,
    columns: layout.promptColumns,
    maxRows: layout.promptRowLimit,
    horizontalPadding: layout.horizontalPadding,
  });

  return React.createElement(
    Box,
    { flexDirection: "column", paddingX: layout.horizontalPadding },
    sessionHeaderVisible
      ? React.createElement(Header, {
          React,
          Box,
          Text,
          compact: layout.compact,
          provider,
          setup: false,
          workspace: process.cwd(),
        })
      : null,
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
          choice: approvalChoice,
          compact: layout.compact,
          showDetails: showApprovalDetails,
        })
      : null,
    React.createElement(StatusLine, {
      React,
      Text,
      elapsedSeconds: activitySeconds,
      frame,
      status,
      statusText,
    }),
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
    !promptVisible
      ? null
      : React.createElement(
          React.Fragment,
          null,
          React.createElement(PromptLine, {
            React,
            Box,
            Text,
            cursor: editor.cursor,
            input: editor.value,
            disabled: promptDisabled,
            columns: layout.promptColumns,
            maxRows: layout.promptRowLimit,
            imeSafe: true,
          }),
          React.createElement(TerminalCursorSync, {
            React,
            control: promptDisabled ? null : promptCursorControl,
          }),
        ),
  );
}

function TerminalCursorSync({
  React,
  control,
}: {
  React: typeof ReactNamespace;
  control: PromptTerminalCursorControl | null;
}): null {
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

function currentTerminalSize(): { columns: number; rows: number } {
  return {
    columns: process.stdout.columns || 80,
    rows: process.stdout.rows || 24,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function isSessionCommandInput(value: string): boolean {
  return !value.includes("\n") && value.trimStart().startsWith("/");
}
