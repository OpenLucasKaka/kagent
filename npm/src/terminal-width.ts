import { splitGraphemes, terminalGraphemeWidth } from "./terminal-text";

export function estimateTextRows(text: string, columns: number): number {
  const safeColumns = Math.max(1, columns);
  return text.split("\n").reduce((total, line) => {
    const width = splitGraphemes(line).reduce(
      (lineWidth, grapheme) => lineWidth + terminalGraphemeWidth(grapheme),
      0,
    );
    return total + Math.max(1, Math.ceil(width / safeColumns));
  }, 0);
}

export { terminalGraphemeWidth } from "./terminal-text";
