export function mergeVisible<T extends { id: string }>(all: T[], visible: T[]) {
  const visibleIds = new Set(visible.map(({ id }) => id));
  const result = all.slice();
  let next = 0;
  for (const [index, item] of all.entries()) {
    if (visibleIds.has(item.id)) result[index] = visible[next++];
  }
  return result;
}
