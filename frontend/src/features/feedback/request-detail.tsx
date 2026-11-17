import { useState } from "react";
import { Button } from "@primer/react";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ArchiveIcon,
  XIcon,
} from "@primer/octicons-react";
import {
  IssueDetail,
  IssueProperty,
  IssueComment,
} from "@/components/issue-detail/issue-detail";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { IssueDiscussion } from "@/components/issue-detail/issue-discussion";
import { rejectRequest } from "./request-decisions";
import { RequestOpportunities } from "./request-opportunities";
import {
  FeedbackSupportButton,
  type FeedbackSupport,
} from "./feedback-support";
import {
  SubmitterFeed,
} from "@/features/updates/submitter-updates";
import type { RequestItem, RequestPatch } from "./request-table";

export function RequestDetail({
  item,
  workspace,
  userId,
  backHref,
  canEdit,
  update,
  onSupport,
  onConfirmed,
  previous,
  next,
  notice,
}: {
  item: RequestItem & FeedbackSupport;
  workspace: string;
  userId: string;
  backHref: string;
  canEdit: boolean;
  update: (ids: string[], patch: RequestPatch) => Promise<void>;
  onSupport: (value: FeedbackSupport) => void;
  onConfirmed: () => void;
  previous?: () => void;
  next?: () => void;
  notice: string;
}) {
  const [approvalTarget, setApprovalTarget] = useState<HTMLSpanElement | null>(
    null,
  );
  const [opportunityTarget, setOpportunityTarget] =
    useState<HTMLDivElement | null>(null);
  const [updatesRevision, setUpdatesRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(patch: RequestPatch) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await update([item.id], patch);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const status =
    (
      {
        new: "New",
        triaged: "Approved",
        rejected: "Rejected",
        needs_clarification: "Needs clarification",
        archived: "Archived",
      } as Record<string, string>
    )[item.status] || item.status;
  const author = item.submitted_by === userId ? "You" : (item.submitter_name || "Workspace member");
  return (
    <IssueDetail
      id={item.id}
      title={item.title}
      status={status}
      backHref={backHref}
      backLabel="Requests"
      subtitle={
        <>
          {author} opened this request ·{" "}
          {new Date(item.created_at).toLocaleDateString()} ·{" "}
          {item.support_count}{" "}
          {item.support_count === 1 ? "supporter" : "supporters"}
        </>
      }
      primaryActions={
        <>
          {canEdit && (
            <>
              <Button
                size="small"
                leadingVisual={item.status === "archived" ? ArchiveIcon : XIcon}
                variant={item.status === "archived" ? "default" : "danger"}
                className={
                  item.status === "archived"
                    ? undefined
                    : "request-reject-button"
                }
                disabled={busy || item.status === "rejected"}
                onClick={() => {
                  if (item.status === "archived") {
                    void save({ archived: false });
                    return;
                  }
                  setBusy(true);
                  setError("");
                  void rejectRequest(item.id, item.status, workspace)
                    .then(onConfirmed)
                    .catch((e) => setError(e.message))
                    .finally(() => setBusy(false));
                }}
              >
                {item.status === "archived" ? "Restore request" : "Reject"}
              </Button>
              <span ref={setApprovalTarget} />
            </>
          )}
        </>
      }
      actions={
        <>
          <Button
            size="small"
            leadingVisual={ArrowLeftIcon}
            aria-label="Previous request"
            disabled={!previous}
            onClick={previous}
          >
            Previous
          </Button>
          <Button
            size="small"
            trailingVisual={ArrowRightIcon}
            aria-label="Next request"
            disabled={!next}
            onClick={next}
          >
            Next
          </Button>
        </>
      }
      sidebar={
        <>
          <IssueProperty label="Status">
            <strong>{status}</strong>
          </IssueProperty>
          <IssueProperty label="Linked opportunity">
            <div ref={setOpportunityTarget} />
          </IssueProperty>
          <IssueProperty label="Submitted by">{author}</IssueProperty>

          {error && (
            <p role="alert" className="issue-notice">
              {error}
            </p>
          )}
        </>
      }
    >
      <IssueComment
        author={author}
        date={item.created_at}
        label="Original feedback"
        headerActions={
          <FeedbackSupportButton
            compact
            requestId={item.id}
            workspace={workspace}
            support={item}
            onChange={onSupport}
          />
        }
      >
        <AnalysisMarkdown>{item.description}</AnalysisMarkdown>
      </IssueComment>

      {notice && (
        <p role="status" className="issue-notice">
          {notice}
        </p>
      )}
      <RequestOpportunities
        key={`links:${workspace}:${item.id}`}
        requestId={item.id}
        workspace={workspace}
        canEdit={canEdit && !busy}
        status={item.status}
        actionsTarget={approvalTarget}
        sidebarTarget={opportunityTarget}
        onConfirmed={onConfirmed}
        onBusyChange={setBusy}
      />
      <SubmitterFeed
        workspace={workspace}
        requestId={item.id}
        revision={updatesRevision}
        showHeading={false}
        onReply={onConfirmed}
      />
      {canEdit && (
        <IssueDiscussion
          key={`${workspace}:${item.id}`}
          threadId={item.id}
          workspace={workspace}
          userId={userId}
          canEdit={canEdit}
          requestStatus={item.status}
          onPublished={() => setUpdatesRevision((v) => v + 1)}
        />
      )}
    </IssueDetail>
  );
}
