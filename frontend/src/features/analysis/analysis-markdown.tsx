import { useId } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import "./analysis-markdown.css";

// Keep this map closed: callers supply text, not plugins, HTML, or renderers.
const components: Components = {
  img: ({ alt }) => (
    <span className="analysis-markdown-image">
      [Image omitted{alt ? `: ${alt}` : ""}]
    </span>
  ),
  table: ({ node: _node, ...props }) => (
    <div
      className="analysis-markdown-table"
      role="region"
      aria-label="Scrollable analysis table"
      tabIndex={0}
    >
      <table {...props} />
    </div>
  ),
  pre: ({ node: _node, ...props }) => (
    <pre {...props} tabIndex={0} aria-label="Code block" />
  ),
};

export function AnalysisMarkdown({
  children,
  className = "",
}: {
  children: string;
  className?: string;
}) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  return (
    <div className={`analysis-markdown ${className}`}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        remarkRehypeOptions={{ clobberPrefix: `analysis-${id}-` }}
        components={{
          ...components,
          h2: ({ node: _node, id: headingId, ...props }) => (
            <h2
              {...props}
              id={
                headingId === "footnote-label"
                  ? `analysis-${id}-footnote-label`
                  : headingId
              }
            />
          ),
          a: ({ node: _node, href, children: label, ...props }) =>
            href ? (
              <a
                {...props}
                href={href}
                aria-describedby={
                  props["aria-describedby"] === "footnote-label"
                    ? `analysis-${id}-footnote-label`
                    : props["aria-describedby"]
                }
              >
                {label}
              </a>
            ) : (
              <span>{label}</span>
            ),
        }}
        skipHtml
      >
        {children}
      </Markdown>
    </div>
  );
}
