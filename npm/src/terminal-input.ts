import { emitKeypressEvents, type Key as ReadlineKey } from "node:readline";
import { PassThrough } from "node:stream";

export type TerminalKey = {
  sequence: string;
  name?: string;
  ctrl: boolean;
  meta: boolean;
  shift: boolean;
};

export type TerminalInputHandler = (input: string, key: TerminalKey) => void;

export type TerminalInputBridge = {
  write: (input: string | Buffer) => void;
  close: () => void;
};

export function createTerminalInputBridge(handler: TerminalInputHandler): TerminalInputBridge {
  const input = new PassThrough();
  input.setEncoding("utf8");
  emitKeypressEvents(input);

  const handleKeypress = (character: string | undefined, key: ReadlineKey): void => {
    const terminalKey: TerminalKey = {
      sequence: key.sequence || "",
      name: key.name,
      ctrl: Boolean(key.ctrl),
      meta: Boolean(key.meta),
      shift: Boolean(key.shift),
    };
    const input = terminalKey.ctrl ? terminalKey.name || "" : printableInput(character);
    handler(input, terminalKey);
  };

  input.on("keypress", handleKeypress);
  return {
    write(chunk) {
      input.write(chunk);
    },
    close() {
      input.removeListener("keypress", handleKeypress);
      input.end();
    },
  };
}

function printableInput(character: string | undefined): string {
  if (!character) {
    return "";
  }
  const codePoint = character.codePointAt(0) || 0;
  return codePoint < 32 || codePoint === 127 ? "" : character;
}
