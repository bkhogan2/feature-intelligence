/** Scroll only the nearest content pane, never the surrounding app frame. */
export function scrollWithinContent(target: HTMLElement | null) {
  if (!target) return;
  for (let pane = target.parentElement; pane; pane = pane.parentElement) {
    if (pane.classList.contains("app-shell")) return;
    if (!/^(auto|scroll)$/.test(getComputedStyle(pane).overflowY)) continue;
    const offset = target.getBoundingClientRect().top - pane.getBoundingClientRect().top - pane.clientTop;
    pane.scrollTo({
      top: Math.max(0, pane.scrollTop + offset - Math.max(0, (pane.clientHeight - target.offsetHeight) / 2)),
      behavior: "instant",
    });
    return;
  }
}
