import React from "react";
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "./lib/auth-context";
import { App } from "./app";
import "./styles.css";
import { migrateLegacySetting, storageKey } from "./lib/app-storage";
migrateLegacySetting("theme", "theme");
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider
      storageKey={storageKey("theme")}
      attribute="class"
      defaultTheme="system"
      enableSystem
    >
      <AuthProvider>
        <App />
      </AuthProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
