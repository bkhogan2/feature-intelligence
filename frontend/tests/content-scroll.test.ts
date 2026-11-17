import { expect, test } from "bun:test";
import { scrollWithinContent } from "../src/lib/content-scroll";

test("comment jump scrolls only its nearest pane, never frame ancestors", () => {
  const calls: unknown[] = [];
  const frame = { classList: { contains: () => true }, parentElement: null };
  const pane = {
    classList: { contains: () => false }, parentElement: frame,
    scrollTop: 100, clientTop: 0, clientHeight: 600,
    getBoundingClientRect: () => ({ top: 44 }),
    scrollTo: (options: unknown) => calls.push(options),
  };
  const target = { parentElement: pane, offsetHeight: 200, getBoundingClientRect: () => ({ top: 844 }) };
  const original = globalThis.getComputedStyle;
  globalThis.getComputedStyle = (() => ({ overflowY: "auto" })) as typeof getComputedStyle;
  try {
    scrollWithinContent(target as unknown as HTMLElement);
    expect(calls).toEqual([{ top: 700, behavior: "instant" }]);
    scrollWithinContent({ ...target, parentElement: frame } as unknown as HTMLElement);
    scrollWithinContent(null);
    expect(calls).toHaveLength(1);
  } finally { globalThis.getComputedStyle = original; }
});
