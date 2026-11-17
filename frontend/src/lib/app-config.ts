import {
  Boxes,
  ListTodo,
  Bell,
  Inbox,
  MessageSquare,
  Folder,
  History,
  Home,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { DEFAULT_SHELL_LAYOUT } from "./shell-layout";

export type ModuleId = "home" | "inbox" | "workspace" | "settings";
export type PageId =
  | "home"
  | "inbox"
  | "feedback"
  | "opportunities"
  | "tasks"
  | "updates"
  | "activity"
  | "settings";
export type AppPage = {
  id: PageId;
  module: ModuleId;
  title: string;
  navigationTitle: string;
  icon: LucideIcon;
};

// Application-owned branding, navigation and presentation. Secrets, tool permissions
// and spending policy belong to the backend, never this public configuration.
export const APP = {
  id: "app-starter",
  name: "Feature Intelligence",
  icon: Boxes,
  workspaceDisplayName: (name: string) =>
    name === "Product feedback preview" ? "Product feedback" : name,
  supportUrl: "#settings",
  layout: DEFAULT_SHELL_LAYOUT,
  navigationPanel: {
    defaultWidth: 224,
    minWidth: 208,
    maxWidth: 480,
    maxViewportRatio: 0.35,
    keyboardStep: 16,
  },
  home: {
    title: "Understand what your customers need.",
    description:
      "Collect feedback and preserve the context behind every request.",
  },
  modules: [
    { id: "inbox", title: "Inbox", href: "#inbox", icon: Inbox },
    { id: "home", title: "Home", href: "#home", icon: Home },
    { id: "workspace", title: "Workspace", href: "#feedback", icon: Folder },
    { id: "settings", title: "Settings", href: "#settings", icon: Settings },
  ] satisfies { id: ModuleId; title: string; href: string; icon: LucideIcon }[],
  pages: [
    {
      id: "inbox",
      module: "inbox",
      title: "Requests",
      navigationTitle: "Requests",
      icon: Inbox,
    },
    {
      id: "feedback",
      module: "workspace",
      title: "Feedback",
      navigationTitle: "Feedback",
      icon: MessageSquare,
    },
    {
      id: "opportunities",
      module: "workspace",
      title: "Opportunities",
      navigationTitle: "Opportunities",
      icon: Boxes,
    },
    {
      id: "tasks",
      module: "workspace",
      title: "Tasks",
      navigationTitle: "Tasks",
      icon: ListTodo,
    },
    {
      id: "updates",
      module: "workspace",
      title: "Notifications",
      navigationTitle: "Notifications",
      icon: Bell,
    },
    {
      id: "home",
      module: "home",
      title: "Home",
      navigationTitle: "Overview",
      icon: Home,
    },
    {
      id: "activity",
      module: "workspace",
      title: "Activity",
      navigationTitle: "Activity",
      icon: History,
    },
    {
      id: "settings",
      module: "settings",
      title: "Settings",
      navigationTitle: "Settings",
      icon: Settings,
    },
  ] satisfies AppPage[],
  assistant: {
    title: "Assistant",
    welcomeTitle: "What can I help you find?",
    welcomeDescription:
      "Discuss requests, opportunities, and tasks, or ask me to open a page.",
    placeholder: "Ask about your workspace…",
    modeLabel: "Read only",
    notice: "Workspace evidence",
    contextNote:
      "Uses the current page and the last six conversation turns. New chat clears history; reloading clears it too. Can read workspace evidence and open app pages. Changes require your actions in the app.",
    starterPrompts: [
      {
        id: "explain-evidence",
        label: "Explain the evidence",
        description: "Understand the selected item and its sources",
        prompt:
          "Explain the currently selected item and the evidence supporting it. Cite your sources and identify any gaps.",
      },
    ],
    panel: {
      defaultWidth: 360,
      minWidth: 280,
      maxWidth: 800,
      maxViewportRatio: 0.6,
      keyboardStep: 16,
    },
  },
};
