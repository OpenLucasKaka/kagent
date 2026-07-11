import { splitGraphemes } from "./editor";

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

export function terminalGraphemeWidth(grapheme: string): number {
  const codePoint = grapheme.codePointAt(0) || 0;
  if (
    codePoint >= 0x1100 &&
    (codePoint <= 0x115f ||
      codePoint === 0x2329 ||
      codePoint === 0x232a ||
      (codePoint >= 0x2e80 && codePoint <= 0xa4cf) ||
      (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
      (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
      (codePoint >= 0xfe10 && codePoint <= 0xfe6f) ||
      (codePoint >= 0xff00 && codePoint <= 0xff60) ||
      (codePoint >= 0x1f300 && codePoint <= 0x1faff))
  ) {
    return 2;
  }
  return 1;
}
