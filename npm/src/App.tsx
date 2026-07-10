import type ReactNamespace from "react";

import {
  createRuntimeSessionClient,
  type RuntimeClientEvent,
  type RuntimeSessionClient,
} from "./runtime-client";
import {
  createProviderSetupState,
  isInputStage,
  maskSecret,
  providerConfiguration,
  providerSetupReducer,
  selectedProvider,
  type ProviderSetupState,
} from "./provider-setup";
import type {
  ApprovalRequiredEvent,
  ProviderSnapshot,
  RuntimeReadyEvent,
} from "./protocol";

type InkApi = {
  Box: ReactNamespace.ElementType;
  Text: ReactNamespace.ElementType;
  useApp: () => { exit: () => void };
  useInput: (handler: (input: string, key: Record<string, boolean | undefined>) => void) => void;
};

type AppProps = {
  React: typeof ReactNamespace;
  Ink: InkApi;
  runtimeSessionFactory?: typeof createRuntimeSessionClient;
};

type Message = {
  role: "user" | "assistant" | "system";
  text: string;
};

type Status = "starting" | "idle" | "thinking" | "approval" | "error";

export type EditorState = {
  value: string;
  cursor: number;
};

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: "grapheme" });

export function KagentInkApp({
  React,
  Ink,
  runtimeSessionFactory = createRuntimeSessionClient,
}: AppProps): ReactNamespace.ReactElement {
  const { Box, Text } = Ink;
  const app = Ink.useApp();
  const [runtime] = React.useState<RuntimeSessionClient>(() => runtimeSessionFactory());
  const [editor, setEditor] = React.useState<EditorState>({ value: "", cursor: 0 });
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [status, setStatus] = React.useState<Status>("starting");
  const [statusText, setStatusText] = React.useState("");
  const [frame, setFrame] = React.useState(0);
  const [approval, setApproval] = React.useState<ApprovalRequiredEvent | null>(null);
  const [showApprovalDetails, setShowApprovalDetails] = React.useState(false);
  const [provider, setProvider] = React.useState<ProviderSnapshot | null>(null);
  const [setup, setSetup] = React.useState<ProviderSetupState | null>(null);

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

  Ink.useInput((value, key) => {
    if (key.ctrl && value === "c") {
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
    key: Record<string, boolean | undefined>,
  ): void {
    if (!setup || setup.stage === "saving") {
      return;
    }
    if (key.escape) {
      if (setup.stage === "provider") {
        app.exit();
      } else {
        setSetup(providerSetupReducer(setup, { type: "back" }));
      }
      return;
    }
    if (setup.stage === "provider") {
      if (key.upArrow) {
        setSetup(providerSetupReducer(setup, { type: "select", offset: -1 }));
      } else if (key.downArrow) {
        setSetup(providerSetupReducer(setup, { type: "select", offset: 1 }));
      } else if (key.return) {
        setSetup(providerSetupReducer(setup, { type: "next" }));
      }
      return;
    }
    if (key.return) {
      const next = providerSetupReducer(setup, { type: "next" });
      setSetup(next);
      if (next.stage === "saving") {
        runtime.configureProvider(providerConfiguration(next), handleProviderEvent);
      }
      return;
    }
    if (key.backspace || key.delete || value === "\b" || value === "\x7f") {
      updateSetupEditor(deleteBeforeCursor);
      return;
    }
    if (key.leftArrow) {
      updateSetupEditor((current) => moveCursor(current, -1));
      return;
    }
    if (key.rightArrow) {
      updateSetupEditor((current) => moveCursor(current, 1));
      return;
    }
    if (value && !key.ctrl && !key.meta) {
      updateSetupEditor((current) => applyInput(current, value));
    }
  }

  function updateSetupEditor(update: (current: EditorState) => EditorState): void {
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
      setMessages((current) =>
        current.concat({ role: "assistant", text: event.answer || fallback }),
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
    setMessages((current) => current.concat({ role: "system", text: message }));
  }

  if (setup) {
    return React.createElement(
      Box,
      { flexDirection: "column", paddingX: 1 },
      React.createElement(Header, { React, Box, Text, provider: null, setup: true }),
      React.createElement(ProviderSetupPanel, {
        React,
        Box,
        Text,
        frame,
        setup,
      }),
    );
  }

  return React.createElement(
    Box,
    { flexDirection: "column", paddingX: 1 },
    React.createElement(Header, { React, Box, Text, provider, setup: false }),
    React.createElement(MessageList, { React, Box, Text, messages }),
    approval
      ? React.createElement(ApprovalPanel, {
          React,
          Box,
          Text,
          approval,
          showDetails: showApprovalDetails,
        })
      : null,
    React.createElement(StatusLine, { React, Text, frame, status, statusText }),
    status === "starting"
      ? null
      : React.createElement(PromptLine, {
          React,
          Box,
          Text,
          cursor: editor.cursor,
          input: editor.value,
          disabled: status === "thinking" || status === "approval",
        }),
  );
}

function Header({
  React,
  Box,
  Text,
  provider,
  setup,
}: RenderProps & { provider: ProviderSnapshot | null; setup: boolean }): ReactNamespace.ReactElement {
  return React.createElement(
    Box,
    { flexDirection: "column", marginBottom: 1 },
    React.createElement(
      Box,
      { flexDirection: "row" },
      React.createElement(Text, { bold: true, color: "cyan" }, "◆ kagent"),
      React.createElement(Text, { color: "gray" }, setup ? "  setup" : "  agent"),
    ),
    provider?.configured
      ? React.createElement(
          Text,
          { color: "gray" },
          `${provider.display_name}${provider.model ? ` · ${provider.model}` : ""}`,
        )
      : null,
  );
}

function ProviderSetupPanel({
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
      React.createElement(Text, { color: "gray" }, "Choose where kagent should think."),
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
      React.createElement(Text, { color: "cyan" }, `${FRAMES[frame]} Saving settings`),
    );
  }

  const field = setupField(setup);
  const displayValue = setup.stage === "api_key" ? maskSecret(setup.editor.value) : setup.editor.value;
  return React.createElement(
    Box,
    { flexDirection: "column" },
    React.createElement(Text, { bold: true }, `Connect ${option.label}`),
    React.createElement(Text, { color: "gray" }, field.hint),
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

function setupField(setup: ProviderSetupState): {
  label: string;
  hint: string;
  placeholder: string;
} {
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
  const required = selectedProvider(setup).api_key_required;
  return {
    label: required ? "API key" : "API key (optional)",
    hint: "Stored locally with owner-only permissions",
    placeholder: required ? "Paste API key" : "Leave empty for local providers",
  };
}

function MessageList({ React, Box, Text, messages }: RenderProps & { messages: Message[] }) {
  const recent = messages.slice(-10);
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...recent.map((message, index) => {
      const marker = message.role === "user" ? "›" : message.role === "assistant" ? "•" : "!";
      const color = message.role === "user" ? "cyan" : message.role === "assistant" ? undefined : "red";
      return React.createElement(
        Box,
        { key: `${message.role}-${index}`, flexDirection: "row", marginBottom: 1 },
        React.createElement(Text, { color, bold: message.role === "user" }, `${marker} `),
        React.createElement(Text, { color, wrap: "wrap" }, message.text),
      );
    }),
  );
}

function ApprovalPanel({
  React,
  Box,
  Text,
  approval,
  showDetails,
}: RenderProps & { approval: ApprovalRequiredEvent; showDetails: boolean }) {
  return React.createElement(
    Box,
    { flexDirection: "column", marginY: 1, paddingLeft: 2 },
    React.createElement(Text, { bold: true, color: "yellow" }, "Permission required"),
    React.createElement(Text, null, approval.title),
    approval.target
      ? React.createElement(Text, { color: "cyan", wrap: "wrap" }, approval.target)
      : null,
    showDetails && approval.reason
      ? React.createElement(Text, { color: "gray", wrap: "wrap" }, approval.reason)
      : null,
    React.createElement(Text, { color: "gray" }, "y allow   n deny   d details"),
  );
}

function StatusLine({
  React,
  Text,
  frame,
  status,
  statusText,
}: StatusRenderProps & { frame: number; status: Status; statusText: string }) {
  if (status !== "thinking" && status !== "starting") {
    return React.createElement(Text, null, "");
  }
  const label = status === "starting" ? "Starting runtime" : statusText;
  return React.createElement(Text, { color: "cyan" }, `${FRAMES[frame]} ${label}`);
}

function PromptLine({
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
  return React.createElement(
    Box,
    { flexDirection: "row", marginTop: compact ? 0 : 1, alignItems: "flex-start" },
    React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "),
    input
      ? React.createElement(
          Text,
          { wrap: "wrap" },
          before,
          React.createElement(Text, { inverse: !disabled }, active),
          after,
        )
      : React.createElement(Text, { color: "gray" }, disabled ? "" : placeholder),
  );
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

export function deleteBeforeCursor(state: EditorState): EditorState {
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

export function applyInput(state: EditorState, rawInput: string): EditorState {
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

export function moveCursor(state: EditorState, offset: number): EditorState {
  const length = splitGraphemes(state.value).length;
  return {
    ...state,
    cursor: Math.min(Math.max(state.cursor + offset, 0), length),
  };
}

export function splitGraphemes(value: string): string[] {
  return Array.from(GRAPHEME_SEGMENTER.segment(value), ({ segment }) => segment);
}
