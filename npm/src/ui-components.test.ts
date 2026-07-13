import assert from "node:assert/strict";
import test from "node:test";

import { createTerminalLayout } from "./ui-components";

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
