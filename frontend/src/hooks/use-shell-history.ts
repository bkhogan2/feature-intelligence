import { useEffect, useState } from "react";

// Bound header navigation to this signed-in workspace session. Never send a
// deep-linked user back to an unrelated site or a previous workspace context.
export function useShellHistory(context: string) {
  const [bounds, setBounds] = useState({ position: 0, maximum: 0 });
  useEffect(() => {
    const session = crypto.randomUUID();
    let position = 0;
    let maximum = 0;
    const mark = () =>
      history.replaceState(
        { ...history.state, starterNavigation: { session, position } },
        "",
      );
    mark();
    setBounds({ position, maximum });
    const update = () => {
      const entry = history.state?.starterNavigation;
      if (entry?.session === session && Number.isInteger(entry.position))
        position = entry.position;
      else {
        position += 1;
        maximum = position;
        mark();
      }
      setBounds({ position, maximum });
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, [context]);
  return {
    canGoBack: bounds.position > 0,
    canGoForward: bounds.position < bounds.maximum,
    back: () => {
      if (bounds.position > 0) history.back();
    },
    forward: () => {
      if (bounds.position < bounds.maximum) history.forward();
    },
  };
}
