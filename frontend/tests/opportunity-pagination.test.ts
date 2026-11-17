import { expect, test } from "bun:test";
import { loadOpportunityPages } from "../src/features/opportunities/opportunity-pagination";

test("loads every server page before exposing the filtered scope", async () => {
  const offsets: number[] = [];
  const rows = Array.from({ length: 235 }, (_, i) => ({ id: `${i}` }));
  const all = await loadOpportunityPages(async (offset) => {
    offsets.push(offset);
    return {
      items: rows.slice(offset, offset + 100),
      has_more: offset + 100 < rows.length,
    };
  });
  expect(offsets).toEqual([0, 100, 200]);
  expect(all).toEqual(rows);
});

test("a failed later page rejects instead of offering a partial all-filtered scope", async () => {
  await expect(
    loadOpportunityPages(async (offset) => {
      if (offset) throw new Error("Network unavailable");
      return { items: [{ id: "first" }], has_more: true };
    }),
  ).rejects.toThrow("Network unavailable");
});

test("nonadvancing and overlapping pages fail explicitly", async () => {
  await expect(
    loadOpportunityPages(async () => ({ items: [], has_more: true })),
  ).rejects.toThrow("pages changed");
  await expect(
    loadOpportunityPages(async () => ({
      items: [{ id: "same" }],
      has_more: true,
    })),
  ).rejects.toThrow("pages changed");
  await expect(
    loadOpportunityPages(async () => ({
      items: [{ id: "same" }, { id: "same" }],
      has_more: false,
    })),
  ).rejects.toThrow("Duplicate");
});
