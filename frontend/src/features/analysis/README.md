# Analysis Markdown

Reusable presentation for future analysis text; it does not generate, store, or validate analysis.

```tsx
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";

<AnalysisMarkdown>{analysisMarkdown}</AnalysisMarkdown>
```

Supply a Markdown string. `className` can set spacing/width on the wrapper. Choose heading levels appropriate to the containing page; semantic headings are preserved. The wrapper has no background so it retains the page's white or dark surface. All text, borders, emphasis and focus styles use existing theme tokens.

Supports paragraphs, headings, ordered/unordered/task lists, quotes, strikethrough, GFM tables, links, inline/fenced code and footnotes. Task checkboxes are display-only. Tables and code blocks have keyboard-focusable horizontal scrolling; long prose wraps. Multiple renderer instances have independent footnote IDs and accessible labels.

Security boundaries:
- Raw HTML is skipped. There is no raw HTML plugin, MDX execution, syntax-highlighting engine or diagram renderer.
- `react-markdown`'s default URL transform stays enabled. Rejected link destinations render as plain text. Accepted links use ordinary same-tab navigation, including fragment links for footnotes.
- All Markdown images render an “Image omitted” text label with escaped alt text, without an image element, preload or remote request.
- Callers cannot inject custom plugins/components through this API. Markdown can still contain misleading prose or links; rendering is not evidence validation or a trust guarantee.

## Local illustrative preview

With the existing frontend development server running, open `/tests/fixtures/analysis.html` (for the current preview: `http://127.0.0.1:5189/tests/fixtures/analysis.html`). It includes a light/dark toggle and a clearly fictional formatting example. No backend/model calls, customer data, product navigation changes or generated triage are involved. This fixture is outside the production entry graph.

## Validation

`bun test tests/analysis-markdown.test.ts` renders real React output and covers supported semantics, safe URL handling, omitted raw HTML/images, literal code/MDX-like text and unique linked footnotes. `bun run build` performs TypeScript checking and the production build.

Dependencies are direct entries in `package.json` and locked in `bun.lock`: react-markdown 10.1.0 and remark-gfm 4.0.1. Implementation follows the upstream [react-markdown](https://github.com/remarkjs/react-markdown) and [remark-gfm](https://github.com/remarkjs/remark-gfm) documentation.
