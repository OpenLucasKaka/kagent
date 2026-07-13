import assert from "node:assert/strict";
import test from "node:test";

import {
  shouldRenderPromptPlaceholder,
  createPromptTerminalCursorControl,
  createTerminalLayout,
} from "./ui-components";

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
