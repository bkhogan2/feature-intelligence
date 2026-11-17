export type PanelSizing = {
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  maxViewportRatio: number;
  keyboardStep: number;
};
export function panelBounds(policy: PanelSizing, viewportWidth: number) {
  return {
    min: policy.minWidth,
    max: Math.max(
      policy.minWidth,
      Math.min(
        policy.maxWidth,
        Math.floor(viewportWidth * policy.maxViewportRatio),
      ),
    ),
  };
}
export function clampPanelWidth(
  value: number,
  policy: PanelSizing,
  viewportWidth: number,
) {
  const { min, max } = panelBounds(policy, viewportWidth);
  return Math.round(
    Math.max(
      min,
      Math.min(Number.isFinite(value) ? value : policy.defaultWidth, max),
    ),
  );
}
export function savedPanelWidth(
  saved: string,
  policy: PanelSizing,
  viewportWidth: number,
) {
  const value = Number(saved);
  return clampPanelWidth(
    value > 0 ? value : policy.defaultWidth,
    policy,
    viewportWidth,
  );
}
