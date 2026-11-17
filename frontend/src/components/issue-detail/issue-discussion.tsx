import { useEffect, useRef, useState } from "react";
import { Button, Timeline } from "@primer/react";
import { IssueMarkdownEditor } from "@/components/issue-detail/issue-markdown-editor";
import { CommentIcon, SparkleIcon } from "@primer/octicons-react";
import { api } from "@/lib/auth-context";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { IssueComment } from "@/components/issue-detail/issue-detail";

type Comment = {
  id: string;
  body: string;
  author_id: string;
  created_at: string;
};
export function IssueDiscussion({
  threadId,
  resource = "feedback",
  workspace,
  userId,
  canEdit,
  requestStatus,
  onPublished,
}: {
  threadId: string;
  resource?: "feedback" | "opportunities" | "tasks";
  workspace: string;
  userId?: string;
  canEdit: boolean;
  requestStatus?: string;
  onPublished?: () => void;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const submission = useRef<{ id: string; body: string } | null>(null);
  const endpoint = `/${resource}/${threadId}/comments`;
  useEffect(() => {
    const controller = new AbortController();
    api<{ items: Comment[] }>(
      endpoint,
      { signal: controller.signal },
      workspace,
    )
      .then((r) => {
        if (!controller.signal.aborted) setComments(r.items);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoadFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [endpoint, workspace]);
  async function draft() {
    setDrafting(true);
    setError("");
    try {
      const result = await api<{ body: string }>(`/feedback/${threadId}/updates/draft`, { method: "POST" }, workspace);
      setBody(result.body);
      setPreview(false);
    } catch (e) { setError((e as Error).message); }
    finally { setDrafting(false); }
  }
  async function submit() {
    if (busy || !body.trim()) return;
    setBusy(true);
    setError("");
    const pending =
      submission.current?.body === body.trim()
        ? submission.current
        : { id: crypto.randomUUID(), body: body.trim() };
    submission.current = pending;
    try {
      if (requestStatus !== undefined) {
        await api(`/feedback/${threadId}/updates`, {
          method: "POST",
          body: JSON.stringify({ ...pending, kind: "update", expected_status: requestStatus }),
        }, workspace);
        onPublished?.();
      } else {
      const saved = await api<Comment>(
        endpoint,
        { method: "POST", body: JSON.stringify(pending) },
        workspace,
      );
      setComments((old) => [...old.filter((c) => c.id !== saved.id), saved]);
      }
      setBody("");
      setPreview(false);
      submission.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Discussion" className="request-comments">
      {loading && <p role="status">Loading comments…</p>}
      {loadFailed && (
        <p role="alert">Could not load comments. Refresh to try again.</p>
      )}
      <Timeline>
        {comments.map((comment) => (
          <Timeline.Item key={comment.id}>
            <Timeline.Badge>
              <CommentIcon />
            </Timeline.Badge>
            <Timeline.Body>
              <IssueComment
                author={
                  comment.author_id === userId ? "You" : comment.author_id
                }
                date={comment.created_at}
                label="Comment"
                neutral
                verb="commented on"
              >
                <AnalysisMarkdown>{comment.body}</AnalysisMarkdown>
              </IssueComment>
            </Timeline.Body>
          </Timeline.Item>
        ))}
      </Timeline>
      {canEdit && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="issue-comment-editor"
        >
          <h2>Add a comment</h2>
          <IssueMarkdownEditor
            label="Comment"
            body={body}
            onChange={setBody}
            preview={preview}
            setPreview={setPreview}
            disabled={busy || drafting}
            toolbarActions={requestStatus !== undefined ? <Button type="button" leadingVisual={SparkleIcon} disabled={busy || drafting || !!body.trim()} onClick={() => void draft()}>{drafting ? "Drafting…" : "Draft"}</Button> : undefined}
            maxLength={requestStatus !== undefined ? 4000 : 10000}
            placeholder="Leave a comment"
          />
          {error && <p role="alert">{error}</p>}
          <div className="issue-comment-submit">
            <Button
              type="submit"
              variant="primary"
              disabled={busy || loading || !body.trim()}
            >
              {busy ? "Commenting…" : "Comment"}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
