import { useCallback, useEffect, useState } from "react";
import { readSetting, writeSetting } from "@/lib/app-storage";
import {
  clampPanelWidth,
  panelBounds,
  savedPanelWidth,
  type PanelSizing,
} from "@/lib/panel-sizing";

export function useResizablePanel(policy: PanelSizing, key: string) {
  const [viewport, setViewport] = useState(window.innerWidth);
  const [width, setWidth] = useState(() =>
    savedPanelWidth(readSetting(key, ""), policy, window.innerWidth),
  );
  const resize = useCallback(
    (value: number) => {
      const next = clampPanelWidth(value, policy, window.innerWidth);
      setWidth(next);
      writeSetting(key, String(next));
    },
    [policy, key],
  );
  useEffect(() => {
    const update = () => {
      setViewport(window.innerWidth);
      setWidth((current) =>
        clampPanelWidth(current, policy, window.innerWidth),
      );
    };
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [policy]);
  return { width, resize, ...panelBounds(policy, viewport) };
}
