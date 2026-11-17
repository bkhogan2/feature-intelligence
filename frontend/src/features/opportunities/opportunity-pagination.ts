/** Load the full server scope before enabling local filters or batch actions. */
export async function loadOpportunityPages<T extends { id: string }>(
  fetchPage: (offset: number) => Promise<{ items: T[]; has_more: boolean }>,
): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  for (;;) {
    const page = await fetchPage(items.length);
    if (
      page.items.some((item) => seen.has(item.id)) ||
      (page.has_more && !page.items.length)
    ) {
      throw new Error(
        "Opportunity pages changed while loading. Reload to get a complete scope.",
      );
    }
    for (const item of page.items) {
      if (seen.has(item.id))
        throw new Error("Duplicate opportunity in response. Reload the list.");
      seen.add(item.id);
      items.push(item);
    }
    if (!page.has_more) return items;
  }
}
