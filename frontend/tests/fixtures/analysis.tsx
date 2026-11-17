// Development-only fixture; no API or model calls, not linked in product nav.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { AnalysisMarkdown } from "../../src/features/analysis/analysis-markdown";
import { analysisExample } from "./analysis-example";
import "../../src/styles.css";

function Fixture() {
  const [dark, setDark] = useState(false);
  return (
    <div className={dark ? "dark" : ""}>
      <main
        style={{
          minHeight: "100vh",
          background: "var(--background)",
          color: "var(--foreground)",
          padding: "24px",
        }}
      >
        <div style={{ maxWidth: "760px", margin: "0 auto" }}>
          <h1 style={{ fontWeight: 600, marginBottom: "12px" }}>
            Analysis renderer preview
          </h1>
          <button
            type="button"
            aria-pressed={dark}
            onClick={() => setDark((value) => !value)}
            style={{
              border: "1px solid var(--border)",
              padding: "6px 12px",
              borderRadius: "6px",
              marginBottom: "24px",
            }}
          >
            Dark appearance
          </button>
          <AnalysisMarkdown>{analysisExample}</AnalysisMarkdown>
        </div>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
