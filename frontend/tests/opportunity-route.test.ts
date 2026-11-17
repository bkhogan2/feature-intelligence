import { expect, test } from "bun:test";
import {
  readOpportunityRoute,
  opportunityHref,
  chooseOpportunityId,
} from "../src/features/opportunities/opportunity-route";
test("status and sorting survive independent navigation with compatible default", () => {
  expect(readOpportunityRoute("#opportunities")).toEqual({
    status: "all",
    sort: "recent",
    id: null,
  });
  const current = readOpportunityRoute(
    "#opportunities?status=shipped&sort=priority&id=first",
  );
  const next = readOpportunityRoute(
    opportunityHref({ ...current, status: "considering", id: null }),
  );
  expect(next).toEqual({ status: "considering", sort: "priority", id: null });
  expect(readOpportunityRoute("#opportunities?status=invalid").status).toBe(
    "all",
  );
});
test("selection respects filter, empty state and direct links beyond newest set", () => {
  const rows = [{ id: "first", status: "shipped" }];
  expect(
    chooseOpportunityId(
      rows,
      { status: "shipped", sort: "priority", id: "excluded" },
      { id: "excluded", status: "considering" },
    ),
  ).toBe("first");
  expect(
    chooseOpportunityId(
      rows,
      { status: "shipped", sort: "recent", id: "older" },
      { id: "older", status: "shipped" },
    ),
  ).toBe("older");
  expect(
    chooseOpportunityId([], { status: "planned", sort: "recent", id: null }),
  ).toBeNull();
});
