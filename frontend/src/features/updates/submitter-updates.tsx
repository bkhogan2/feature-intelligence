import { scrollWithinContent } from "@/lib/content-scroll";
import { UpdatesTable } from "./updates-table";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { IssueMarkdownEditor } from "@/components/issue-detail/issue-markdown-editor";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { IssueComment } from "@/components/issue-detail/issue-detail";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { api } from "@/lib/auth-context";

const maxLength = 4000;
type Message = {
  id: string;
  feedback_id: string;
  opportunity_id: string | null;
  kind: "update" | "clarification" | "receipt";
  body: string;
  created_at: string;
  request_title: string;
  request_status: string;
  is_recipient: boolean;
  sent_by_you: boolean;
  latest_question: boolean;
  reply: string | null;
  replied_at: string | null;
};
type Feed = { items: Message[]; has_more: boolean };
type Target =
  | { type: "feedback"; id: string; status: string }
  | {
      type: "opportunities";
      id: string;
      status: string;
      requestIds: string[];
      requests?: { id: string; title: string }[];
    };

export function SubmitterComposer({
  workspace,
  target,
  onPublished,
  clarification = false,
  disabled = false,
}: {
  workspace: string;
  target: Target;
  onPublished?: () => void;
  clarification?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState<"draft" | "publish" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [publicationId, setPublicationId] = useState("");
  const [snapshot, setSnapshot] = useState(target);
  const count =
    snapshot.type === "opportunities" ? snapshot.requestIds.length : 1;
  const title = clarification
    ? "Ask for clarification"
    : "Draft update to submitters";
  const pathname = `/${snapshot.type}/${snapshot.id}/updates`;

  async function draft() {
    setBusy("draft");
    setError("");
    try {
      const result = await api<{ body: string }>(
        `${pathname}/draft`,
        { method: "POST" },
        workspace,
      );
      setBody(result.body);
      setPublicationId(crypto.randomUUID());
      setPreview(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function publish() {
    setBusy("publish");
    setError("");
    try {
      const result = await api<{ request_count: number }>(
        pathname,
        {
          method: "POST",
          body: JSON.stringify({
            id: publicationId,
            kind: clarification ? "clarification" : "update",
            body,
            expected_status: snapshot.status,
            expected_requests:
              snapshot.type === "opportunities"
                ? snapshot.requestIds
                : undefined,
          }),
        },
        workspace,
      );
      setOpen(false);
      setNotice(
        clarification
          ? "Question sent. The submitter can reply in this request’s conversation."
          : `Update published for ${result.request_count} linked ${result.request_count === 1 ? "request" : "requests"}.`,
      );
      onPublished?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2">
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (busy) return;
          if (next) {
            setSnapshot(target);
            setPublicationId(crypto.randomUUID());
            setBody("");
            setPreview(false);
            setError("");
            setNotice("");
          }
          setOpen(next);
        }}
      >
        <DialogTrigger asChild>
          <Button variant="outline" size="sm" disabled={disabled}>
            {title}
          </Button>
        </DialogTrigger>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {clarification
                ? "Visible to the original submitter and reviewers in this request’s conversation. Their reply returns the request to New."
                : snapshot.type === "opportunities"
                  ? `This will be published in the conversations of ${count} linked ${count === 1 ? "request" : "requests"}.`
                  : "Visible to the original submitter and reviewers in this request’s conversation. They can find it in Updates."}
            </DialogDescription>
          </DialogHeader>
          {snapshot.type === "opportunities" && snapshot.requests && (
            <div className="space-y-1 text-sm">
              <p className="font-medium">
                Recipients: original submitters of these requests
              </p>
              {snapshot.requests.map((request) => (
                <p key={request.id}>{request.title}</p>
              ))}
            </div>
          )}
          <IssueMarkdownEditor
            label={
              clarification ? "Question for the submitter" : "Submitter update"
            }
            body={body}
            onChange={(value) => {
              setBody(value);
              setPublicationId(crypto.randomUUID());
            }}
            preview={preview}
            setPreview={setPreview}
            disabled={!!busy}
            maxLength={maxLength}
            placeholder={
              clarification
                ? "What details would help you understand this request?"
                : "What should the submitter know about this decision or progress?"
            }
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            {!clarification && !preview && (
              <Button
                variant="outline"
                disabled={!!busy || !!body.trim()}
                onClick={() => void draft()}
              >
                {busy === "draft" ? "Drafting…" : "Draft with AI"}
              </Button>
            )}
            <Button
              disabled={!!busy || !body.trim() || !count}
              onClick={() => {
                if (!preview) setPreview(true);
                else void publish();
              }}
            >
              {busy === "publish"
                ? "Publishing…"
                : preview
                  ? clarification
                    ? "Publish question"
                    : "Publish update"
                  : "Review before publishing"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {notice && (
        <p role="status" className="text-xs text-muted-foreground">
          {notice}
        </p>
      )}
    </div>
  );
}

function UpdateCard({
  item,
  workspace,
  inline,
  onReply,
}: {
  item: Message;
  workspace: string;
  inline: boolean;
  onReply: () => void;
}) {
  const [reply, setReply] = useState("");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const awaitingReply =
    item.kind === "clarification" &&
    item.latest_question &&
    !item.reply &&
    item.request_status === "needs_clarification";
  const timestamp = new Date(item.created_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  async function submitReply() {
    setBusy(true);
    setError("");
    try {
      await api(
        `/updates/${item.id}/reply`,
        {
          method: "POST",
          body: JSON.stringify({ body: reply }),
        },
        workspace,
      );
      setReply("");
      onReply();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!inline)
    return (
      <Card>
        <CardHeader>
          <CardDescription>
            {awaitingReply
              ? item.is_recipient
                ? "Reply requested"
                : "Waiting for submitter"
              : item.reply
                ? "Reply received"
                : "Update published"}
            {" · "}
            {item.is_recipient ? "Your request" : "Reviewing"}
            {" · "}
            {timestamp}
          </CardDescription>
          <CardTitle>
            <a
              href={`#inbox?status=all&id=${item.feedback_id}`}
              className="hover:underline"
            >
              {item.request_title}
            </a>
          </CardTitle>
          <CardDescription className="line-clamp-2">
            {item.reply || item.body}
          </CardDescription>
          <Button asChild variant="link" size="sm" className="self-start px-0">
            <a href={`#inbox?status=all&id=${item.feedback_id}`}>
              {awaitingReply && item.is_recipient
                ? "Open request to reply"
                : "Open conversation"}
            </a>
          </Button>
        </CardHeader>
      </Card>
    );
  return (
    <IssueComment
      neutral
      id={`comment-${item.id}`}
      author={item.kind === "receipt" ? "Feature Intelligence" : item.sent_by_you ? "You" : "Reviewer"}
      date={item.created_at}
      verb="commented on"
      label="Comment"
    >
      <AnalysisMarkdown>{item.body}</AnalysisMarkdown>
      {item.reply && (
        <div className="mt-3 border-l-2 pl-3">
          <p className="mb-1 text-xs font-semibold text-muted-foreground">
            {item.is_recipient ? "Your reply" : "Submitter’s reply"}
          </p>
          <AnalysisMarkdown>{item.reply}</AnalysisMarkdown>
        </div>
      )}
      {awaitingReply &&
        (item.is_recipient ? (
          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              void submitReply();
            }}
          >
            <IssueMarkdownEditor
              label="Your reply"
              body={reply}
              onChange={setReply}
              preview={preview}
              setPreview={setPreview}
              disabled={busy}
              maxLength={maxLength}
              placeholder="Reply to the reviewer’s question"
            />
            <Button size="sm" type="submit" disabled={busy || !reply.trim()}>
              {busy ? "Sending…" : "Send reply"}
            </Button>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </form>
        ) : (
          <p className="mt-3 text-xs font-medium text-muted-foreground">
            Waiting for the submitter’s reply
          </p>
        ))}
    </IssueComment>
  );
}

export function SubmitterFeed({
  workspace,
  requestId,
  revision = 0,
  onReply,
  reviewer = false,
  showHeading = true,
}: {
  workspace: string;
  requestId?: string;
  revision?: number;
  onReply?: () => void;
  reviewer?: boolean;
  showHeading?: boolean;
}) {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [mine, setMine] = useState(true);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ offset: String(page * 50) });
    if (requestId) query.set("feedback_id", requestId);
    else if (mine) query.set("mine", "true");
    setLoading(true);
    setError("");
    void api<Feed>(
      `/updates?${query}`,
      { signal: controller.signal },
      workspace,
    )
      .then(
        async (result) => {
          const comment = new URLSearchParams(
            window.location.hash.split("?")[1],
          ).get("comment");
          let next = result;
          let offset = page * 50;
          while (
            requestId &&
            comment &&
            next.has_more &&
            !result.items.some((item) => item.id === comment)
          ) {
            offset += 50;
            const more = new URLSearchParams({
              feedback_id: requestId,
              offset: String(offset),
            });
            next = await api<Feed>(
              `/updates?${more}`,
              { signal: controller.signal },
              workspace,
            );
            result = {
              items: [...result.items, ...next.items],
              has_more: next.has_more,
            };
          }
          if (!controller.signal.aborted) setFeed(result);
        },
        (e) => {
          if (!controller.signal.aborted) {
            setError(e.message);
            setFeed(null);
          }
        },
      )
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
          setFeed(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace, requestId, revision, refresh, page, mine]);

  useEffect(() => {
    if (!requestId || !feed) return;
    const comment = new URLSearchParams(window.location.hash.split("?")[1]).get(
      "comment",
    );
    if (comment && feed.items.some((item) => item.id === comment)) {
      scrollWithinContent(document.getElementById(`comment-${comment}`));
    }
  }, [requestId, feed]);

  if (requestId && !feed?.items.length && !error) return null;
  return (
    <section className="space-y-3" aria-label="Messages to submitter">
      {requestId && showHeading && (
        <h2 className="text-sm font-semibold">Messages with the submitter</h2>
      )}
      {!requestId && reviewer && (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={!mine ? "secondary" : "ghost"}
            aria-pressed={!mine}
            onClick={() => {
              setPage(0);
              setMine(false);
            }}
          >
            All request conversations
          </Button>
          <Button
            size="sm"
            variant={mine ? "secondary" : "ghost"}
            aria-pressed={mine}
            onClick={() => {
              setPage(0);
              setMine(true);
            }}
          >
            Updates for me
          </Button>
        </div>
      )}
      {loading ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading updates…
        </p>
      ) : error ? (
        <div>
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          <Button variant="ghost" onClick={() => setRefresh((n) => n + 1)}>
            Retry
          </Button>
        </div>
      ) : feed?.items.length ? (
        feed.items.map((item) => (
          <UpdateCard
            key={item.id}
            item={item}
            inline={!!requestId}
            workspace={workspace}
            onReply={() => {
              setRefresh((n) => n + 1);
              onReply?.();
            }}
          />
        ))
      ) : (
        <p className="rounded-lg border p-4 text-sm text-muted-foreground">
          No updates yet.
        </p>
      )}
      {(page > 0 || feed?.has_more) && (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={loading || page === 0}
            onClick={() => setPage((n) => n - 1)}
          >
            Newer
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={loading || !feed?.has_more}
            onClick={() => setPage((n) => n + 1)}
          >
            Older
          </Button>
        </div>
      )}
    </section>
  );
}

export function UpdatesPage({
  workspace,
}: {
  workspace: string;
  role: string;
}) {
  return <UpdatesTable key={workspace} workspace={workspace} />;
}
