import { describe, expect, test } from "bun:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalysisMarkdown } from "../src/features/analysis/analysis-markdown";
import { analysisExample } from "./fixtures/analysis-example";

const render = (text: string) =>
  renderToStaticMarkup(createElement(AnalysisMarkdown, { children: text }));

describe("analysis Markdown rendering", () => {
  test("renders semantic GFM content, read-only tasks, code and footnotes", () => {
    const html = render(analysisExample);
    for (const tag of [
      "h2",
      "h3",
      "p",
      "ul",
      "ol",
      "blockquote",
      "table",
      "thead",
      "tbody",
      "th",
      "td",
      "pre",
      "code",
      "sup",
      "del",
    ])
      expect(html).toContain(`<${tag}`);
    expect(html).toContain('type="checkbox"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('checked=""');
    expect(html).toContain('data-footnotes="true"');
    expect(html).toContain('role="region"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('href="https://commonmark.org/help/"');
    expect(html).toContain('href="/#inbox"');
  });
  test("does not render HTML, executable URLs, images or image preloads", () => {
    const html = render(
      '<script>alert(1)</script>\n\n<img src="https://example.invalid/raw" onerror="alert(1)">\n\n[bad](javascript:alert%281%29) [data](data:text/html,unsafe)\n\n![Tracking pixel](https://example.invalid/pixel)',
    );
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<link");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("data:text");
    expect(html).not.toContain("https://example.invalid");
    expect(html).toContain("[Image omitted: Tracking pixel]");
    expect(html).toContain("<span>bad</span>");
  });
  test("keeps footnote IDs unique when multiple analyses share a page", () => {
    const html = renderToStaticMarkup(
      createElement(
        "div",
        null,
        createElement(AnalysisMarkdown, {
          children: "One[^same]\n\n[^same]: First source.",
        }),
        createElement(AnalysisMarkdown, {
          children: "Two[^same]\n\n[^same]: Second source.",
        }),
      ),
    );
    const ids = [...html.matchAll(/ id="([^"]+)"/g)].map((match) => match[1]);
    expect(new Set(ids).size).toBe(ids.length);
    for (const match of html.matchAll(/href="#([^"]+)"/g))
      expect(ids).toContain(match[1]);
  });
  test("treats code and MDX-looking expressions as text", () => {
    const html = render(
      '`<script>bad()</script>`\n\n{dangerousFunction()}\n\n```js\nconsole.log("example");\n```',
    );
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("{dangerousFunction()}");
    expect(html).toContain("language-js");
    expect(html).not.toContain("<script>");
  });
});
