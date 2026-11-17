import { useState } from "react";
import { Button } from "@primer/react";
import { PencilIcon } from "@primer/octicons-react";
import { IssueComment } from "@/components/issue-detail/issue-detail";
import { IssueMarkdownEditor } from "@/components/issue-detail/issue-markdown-editor";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { api } from "@/lib/auth-context";

export type DescriptionFields = {
  description_markdown: string | null;
  description_revision: number;
};

export function OpportunityDescription({
  id,
  author,
  date,
  markdown,
  revision,
  canEdit,
  workspace,
  onSave,
  actionRef,
}: {
  id: string;
  author: string;
  date: string;
  markdown: string;
  revision: number;
  canEdit: boolean;
  workspace: string;
  onSave: (value: DescriptionFields) => void;
  actionRef?: (element: HTMLDivElement | null) => void;
}) {
  const [draft, setDraft] = useState<{ body: string; revision: number } | null>(
    null,
  );
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (!draft?.body.trim() || busy || !canEdit || draft.body.length > 20000)
      return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<DescriptionFields>(
        `/opportunities/${id}/description`,
        {
          method: "PUT",
          body: JSON.stringify({
            markdown: draft.body,
            expected_revision: draft.revision,
          }),
        },
        workspace,
      );
      onSave(updated);
      setDraft(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <IssueComment
      author={author}
      date={date}
      label="Opportunity description"
      headerActions={
        canEdit &&
        !draft && (
          <Button
            size="small"
            variant="invisible"
            leadingVisual={PencilIcon}
            onClick={() => {
              setPreview(false);
              setError("");
              setDraft({ body: markdown, revision });
            }}
          >
            Edit description
          </Button>
        )
      }
    >
      {draft ? (
        <form
          className="issue-comment-editor"
          aria-label="Edit opportunity description"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <IssueMarkdownEditor
            label="Description"
            body={draft.body}
            onChange={(body) => setDraft({ ...draft, body })}
            preview={preview}
            setPreview={setPreview}
            disabled={busy}
            maxLength={20000}
          />
          {error && <p role="alert">{error}</p>}
          <div className="issue-comment-submit gap-2">
            <Button
              type="button"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={
                busy ||
                !canEdit ||
                !draft.body.trim() ||
                draft.body.length > 20000
              }
            >
              {busy ? "Saving…" : "Save description"}
            </Button>
          </div>
        </form>
      ) : (
        <>
          <AnalysisMarkdown>{markdown}</AnalysisMarkdown>
          {actionRef && (
            <div ref={actionRef} className="mt-4 flex items-center gap-2" />
          )}
        </>
      )}
    </IssueComment>
  );
}
