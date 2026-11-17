import {
  parseShellHeaderStyle,
  type ShellHeaderStyle,
  parseShellRails,
  type ShellRails,
  parseShellHeader,
  type ShellHeader,
  type ShellLayout,
} from "@/lib/shell-layout";
import { readSetting, writeSetting } from "@/lib/app-storage";
import { api } from "@/lib/auth-context";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";

export function useAppearance(subject: string | undefined) {
  const [loadError, setLoadError] = useState("");
  const [background, setBackground] = useState(() =>
    readSetting("background", "neutral"),
  );
  const layout: ShellLayout = "no-inset";
  const [rails, setRails] = useState<ShellRails>(() =>
    parseShellRails(readSetting("shell-rails", "none")),
  );
  useEffect(() => writeSetting("shell-rails", rails), [rails]);
  const [headerStyle, setHeaderStyle] = useState<ShellHeaderStyle>(() =>
    parseShellHeaderStyle(readSetting("shell-header-style", "standard")),
  );
  useEffect(
    () => writeSetting("shell-header-style", headerStyle),
    [headerStyle],
  );
  const [header, setHeader] = useState<ShellHeader>(() =>
    parseShellHeader(readSetting("shell-header", "content")),
  );
  useEffect(() => writeSetting("shell-header", header), [header]);
  const [rightSidebarEnabled, setRightSidebarEnabled] = useState(
    () => readSetting("right-sidebar-enabled", "true") !== "false",
  );
  useEffect(
    () => writeSetting("right-sidebar-enabled", String(rightSidebarEnabled)),
    [rightSidebarEnabled],
  );
  const [inset, setInset] = useState(() => readSetting("inset", "plain"));
  const { resolvedTheme, setTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const chosenBy = useRef<string | undefined>(undefined);
  const applySavedTheme = useRef(setTheme);
  applySavedTheme.current = setTheme;
  useEffect(() => {
    setLoadError("");
    if (!subject) return;
    let alive = true;
    api<{
      appearance_mode: string;
      background_palette: string;
      inset_style: string;
    }>("/me/preferences")
      .then((p) => {
        if (alive) {
          if (chosenBy.current !== subject) {
            applySavedTheme.current(p.appearance_mode);
          }
          setBackground(p.background_palette);
          setInset(p.inset_style);
        }
      })
      .catch(() => {
        if (alive) setLoadError("Could not load saved appearance.");
      });
    return () => {
      alive = false;
      if (chosenBy.current === subject) chosenBy.current = undefined;
    };
  }, [subject]);
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.palette = "slate";
    root.dataset.backgroundPalette = background;
    root.dataset.insetStyle = inset;
    try {
      writeSetting("background", background);
      writeSetting("inset", inset);
    } catch {}
  }, [background, inset]);
  async function saveAppearance() {
    await api("/me/preferences", {
      method: "PATCH",
      body: JSON.stringify({ appearance_mode: theme }),
    });
  }
  return {
    loadError,
    layout,
    rails,
    setRails,
    headerStyle,
    setHeaderStyle,
    header,
    setHeader,
    rightSidebarEnabled,
    setRightSidebarEnabled,
    theme,
    setTheme: (mode: "light" | "dark") => {
      chosenBy.current = subject;
      setTheme(mode);
    },
    saveAppearance,
  };
}
export type AppearanceController = ReturnType<typeof useAppearance>;
