import assert from "node:assert/strict";
import test from "node:test";

import {
  estimateRuntimeActivityRows,
  RuntimeActivityWorkspace,
  shouldRenderInkPromptCursor,
  shouldRenderPromptPlaceholder,
  createPromptTerminalCursorControl,
  createTerminalLayout,
} from "./ui-components";
import { createRuntimeActivityState } from "./activity";
import { estimateTextRows } from "./terminal-width";

test("does not reserve session header rows after the intro has been shown", () => {
  type LayoutOverlays = Parameters<typeof createTerminalLayout>[2] & {
    introVisible: boolean;
  };
  const withIntroOverlay: LayoutOverlays = {
    approval: false,
    commandMenu: false,
    introVisible: true,
    prompt: "",
    promptCursor: 0,
  };
  const withoutIntroOverlay: LayoutOverlays = {
    approval: false,
    commandMenu: false,
    introVisible: false,
    prompt: "",
    promptCursor: 0,
  };
  const withIntro = createTerminalLayout(100, 30, {
    ...withIntroOverlay,
  });
  const withoutIntro = createTerminalLayout(100, 30, {
    ...withoutIntroOverlay,
  });

  assert.equal(withIntro.reservedRows - withoutIntro.reservedRows, 3);
});

test("reserves the compact and wide runtime activity workspace heights", () => {
  const activity = {
    ...createRuntimeActivityState(),
    phase: "Creating the release notes",
    detail: "Summarising the completed work",
    latestOutcome: "Updated docs/release-notes.md",
    completedCount: 2,
  };

  assert.equal(estimateRuntimeActivityRows(activity, 40, true), 3);
  assert.equal(estimateRuntimeActivityRows(activity, 56, false), 4);
  assert.equal(estimateRuntimeActivityRows(activity, 100, false), 4);
  assert.equal(
    estimateRuntimeActivityRows({
      ...activity,
      expanded: true,
      timeline: [
        { title: "Checked changelog", detail: "README.md" },
        { title: "Wrote release notes", detail: "docs/release-notes.md" },
      ],
    }, 100, false),
    6,
  );
});

test("limits runtime activity rows before approval and prompt space", () => {
  const activity = {
    ...createRuntimeActivityState(),
    phase: "Writing response",
    detail: "A detailed update",
    latestOutcome: "Updated status",
    completedCount: 2,
  };
  const layout = createTerminalLayout(40, 10, {
    approval: true,
    commandMenu: false,
    activity,
    prompt: "",
    promptCursor: 0,
  });

  assert.equal(layout.activityRowLimit, 1);
  assert.ok(layout.reservedRows <= 9);
  assert.ok(layout.promptRowLimit >= 1);
});

test("keeps long CJK and ASCII runtime phases visible within their constrained row budgets", () => {
  for (const [phase, visible] of [
    ["正在整理一份非常长的运行状态说明，确保审批和输入区域始终可见", "正在整理"],
    ["Preparing a detailed runtime status update while approval and prompt remain visible", "Preparing"],
  ]) {
    const activity = { ...createRuntimeActivityState(), phase };
    const layout = createTerminalLayout(40, 10, {
      approval: true,
      commandMenu: false,
      activity,
      prompt: "",
      promptCursor: 0,
    });
    const text: string[] = [];
    const React = {
      createElement(type: unknown, props: unknown, ...children: unknown[]) {
        if (typeof type === "function") {
          return (type as (componentProps: unknown) => unknown)({
            ...(props && typeof props === "object" ? props : {}),
            children,
          });
        }
        text.push(...children.filter((child): child is string => typeof child === "string"));
        return { type, props, children };
      },
    };

    RuntimeActivityWorkspace({
      React: React as never,
      Box: "Box" as never,
      Text: "Text" as never,
      activity,
      compact: true,
      frame: 0,
      elapsedSeconds: 4,
      maxRows: layout.activityRowLimit ?? 0,
      columns: layout.columns,
    });

    const rendered = text.join("");
    assert.match(rendered, new RegExp(visible));
    assert.ok(estimateTextRows(rendered, layout.columns) <= layout.activityRowLimit!);
  }
});

test("renders runtime activity details and only the newest expanded timeline entries", () => {
  const activity = {
    ...createRuntimeActivityState(),
    phase: "Writing response",
    detail: "Answering in Chinese: 正在整理",
    latestOutcome: "Created summary",
    completedCount: 3,
    expanded: true,
    timeline: [
      { title: "Old entry", detail: "hidden" },
      { title: "Recent entry", detail: "one" },
      { title: "Newest entry", detail: "two" },
    ],
  };
  const text: string[] = [];
  const React = {
    createElement(type: unknown, props: unknown, ...children: unknown[]) {
      if (typeof type === "function") {
        return (type as (componentProps: unknown) => unknown)({
          ...(props && typeof props === "object" ? props : {}),
          children,
        });
      }
      text.push(...children.filter((child): child is string => typeof child === "string"));
      return { type, props, children };
    },
  };

  RuntimeActivityWorkspace({
    React: React as never,
    Box: "Box" as never,
    Text: "Text" as never,
    activity,
    compact: false,
    frame: 0,
    elapsedSeconds: 4,
    maxRows: 6,
  });

  const rendered = text.join(" ");
  assert.match(rendered, /Writing response · 4s/);
  assert.match(rendered, /Answering in Chinese: 正在整理/);
  assert.match(rendered, /Created summary/);
  assert.match(rendered, /3 completed · Ctrl\+O details · Esc stop/);
  assert.doesNotMatch(rendered, /Old entry/);
  assert.match(rendered, /Recent entry · one/);
  assert.match(rendered, /Newest entry · two/);
});

test("positions the real terminal cursor on the empty prompt input cell", () => {
  assert.deepEqual(
    createPromptTerminalCursorControl({
      input: "",
      cursor: 0,
      columns: 80,
      maxRows: 6,
      horizontalPadding: 1,
    }),
    {
      position: "\u001b[?25h\u001b[1A\u001b[3C",
      restore: "\r\u001b[1B",
    },
  );
});

test("positions the real terminal cursor on wrapped prompt input", () => {
  assert.deepEqual(
    createPromptTerminalCursorControl({
      input: "abcde",
      cursor: 5,
      columns: 5,
      maxRows: 6,
      horizontalPadding: 0,
    }),
    {
      position: "\u001b[?25h\u001b[1A\u001b[2C",
      restore: "\r\u001b[1B",
    },
  );
});

test("restores from an upper prompt cursor row before the next Ink render", () => {
  assert.deepEqual(
    createPromptTerminalCursorControl({
      input: "abcdef",
      cursor: 2,
      columns: 5,
      maxRows: 6,
      horizontalPadding: 0,
    }),
    {
      position: "\u001b[?25h\u001b[2A\u001b[4C",
      restore: "\r\u001b[2B",
    },
  );
});

test("hides the empty prompt placeholder when IME-safe rendering is enabled", () => {
  assert.equal(
    shouldRenderPromptPlaceholder({
      input: "",
      disabled: false,
      imeSafe: true,
    }),
    false,
  );
});

test("keeps the empty prompt placeholder for normal prompts", () => {
  assert.equal(
    shouldRenderPromptPlaceholder({
      input: "",
      disabled: false,
      imeSafe: false,
    }),
    true,
  );
});

test("does not render the Ink prompt cursor when IME-safe terminal cursor sync is active", () => {
  assert.equal(
    shouldRenderInkPromptCursor({
      input: "测试",
      disabled: false,
      imeSafe: true,
    }),
    false,
  );
});

test("keeps the Ink prompt cursor for normal prompts", () => {
  assert.equal(
    shouldRenderInkPromptCursor({
      input: "test",
      disabled: false,
      imeSafe: false,
    }),
    true,
  );
});
