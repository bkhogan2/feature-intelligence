import type { ReactNode } from "react";
import { FormControl, Textarea, UnderlineNav } from "@primer/react";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";

export function IssueMarkdownEditor({
  label,
  body,
  onChange,
  preview,
  setPreview,
  disabled,
  maxLength,
  placeholder,
  toolbarActions,
}: {
  label: string;
  body: string;
  onChange: (value: string) => void;
  preview: boolean;
  setPreview: (value: boolean) => void;
  disabled: boolean;
  maxLength: number;
  placeholder?: string;
  toolbarActions?: ReactNode;
}) {
  return (
    <>
      <div className="issue-editor-toolbar">
      <UnderlineNav aria-label={`${label} editor`}>
        <UnderlineNav.Item
          as="button"
          type="button"
          aria-current={!preview ? "page" : undefined}
          onClick={() => setPreview(false)}
        >
          Write
        </UnderlineNav.Item>
        <UnderlineNav.Item
          as="button"
          type="button"
          aria-current={preview ? "page" : undefined}
          onClick={() => setPreview(true)}
        >
          Preview
        </UnderlineNav.Item>
      </UnderlineNav>
      {toolbarActions}
      </div>
      {preview ? (
        <div className="issue-comment-preview">
          <AnalysisMarkdown>{body || "Nothing to preview."}</AnalysisMarkdown>
        </div>
      ) : (
        <FormControl disabled={disabled}>
          <FormControl.Label visuallyHidden>{label}</FormControl.Label>
          <Textarea
            aria-label={label}
            block
            rows={6}
            maxLength={maxLength}
            value={body}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
          />
          <FormControl.Caption>Markdown is supported.</FormControl.Caption>
        </FormControl>
      )}
    </>
  );
}
