export const opportunityStatuses = {
  all: "All opportunities",
  considering: "Considering",
  planned: "Planned",
  in_progress: "In progress",
  shipped: "Shipped",
  not_pursuing: "Not pursuing",
} as const;
export type OpportunityFilter = keyof typeof opportunityStatuses;
export type OpportunityRoute = {
  status: OpportunityFilter;
  sort: "recent" | "priority";
  id: string | null;
};
export function readOpportunityRoute(hash: string): OpportunityRoute {
  const params = new URLSearchParams(hash.split("?")[1] ?? "");
  const status = params.get("status") ?? "all";
  return {
    status: Object.hasOwn(opportunityStatuses, status)
      ? (status as OpportunityFilter)
      : "all",
    sort: params.get("sort") === "priority" ? "priority" : "recent",
    id: params.get("id"),
  };
}
export function opportunityHref(route: OpportunityRoute) {
  const params = new URLSearchParams();
  if (route.status !== "all") params.set("status", route.status);
  if (route.sort !== "recent") params.set("sort", route.sort);
  if (route.id) params.set("id", route.id);
  return `#opportunities${params.size ? `?${params}` : ""}`;
}
export function chooseOpportunityId(
  items: { id: string; status: string }[],
  route: OpportunityRoute,
  linked?: { id: string; status: string } | null,
) {
  const requested = items.find((item) => item.id === route.id) ?? linked;
  return requested &&
    (route.status === "all" || requested.status === route.status)
    ? requested.id
    : (items[0]?.id ?? null);
}
