import { Select, Textarea } from "@primer/react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { IssueProperty } from "@/components/issue-detail/issue-detail";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { api } from "@/lib/auth-context";

type SavedOutcome = {
  outcome_status: string;
  outcome_evidence: string;
  outcome_revision: number;
};
const labels: Record<string, string> = {
  not_measured: "Not yet measured",
  improved: "Improved",
  partly_improved: "Partly improved",
  did_not_improve: "Didn’t improve",
};

export function OutcomeCheck({
  workspace,
  id,
  initial,
  editable,
}: {
  workspace: string;
  id: string;
  initial: SavedOutcome;
  editable: boolean;
}) {
  const [saved, setSaved] = useState(initial);
  const [status, setStatus] = useState(initial.outcome_status);
  const [evidence, setEvidence] = useState(initial.outcome_evidence);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function save() {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const current = await api<SavedOutcome>(
        `/opportunities/${id}/outcome`,
        {
          method: "PUT",
          body: JSON.stringify({
            status,
            evidence,
            expected_revision: saved.outcome_revision,
          }),
        },
        workspace,
      );
      setSaved(current);
      setEvidence(current.outcome_evidence);
      setNotice("Outcome saved.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <IssueProperty label="Did this solve the problem?">
      {editable ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Select
            block
            aria-label="Outcome"
            className="w-full rounded-md border bg-background p-2 text-sm"
            value={status}
            disabled={busy}
            onChange={(event) => {
              setStatus(event.target.value);
              setNotice("");
            }}
          >
            {Object.entries(labels).map(([key, label]) => (
              <Select.Option key={key} value={key}>
                {label}
              </Select.Option>
            ))}
          </Select>
          <label
            className="block text-xs font-medium"
            htmlFor="outcome-evidence"
          >
            Evidence link or short note
          </label>
          <Textarea
            block
            id="outcome-evidence"
            className="w-full rounded-md border bg-background p-2 text-sm"
            rows={3}
            maxLength={2000}
            value={evidence}
            disabled={busy}
            onChange={(event) => {
              setEvidence(event.target.value);
              setNotice("");
            }}
          />
          <Button
            size="sm"
            variant="outline"
            type="submit"
            disabled={
              busy ||
              (status === saved.outcome_status &&
                evidence === saved.outcome_evidence) ||
              (status !== "not_measured" && !evidence.trim())
            }
          >
            {busy ? "Saving…" : "Save outcome"}
          </Button>
          {notice && (
            <p role="status" className="text-xs text-muted-foreground">
              {notice}
            </p>
          )}
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </form>
      ) : (
        <div className="space-y-2">
          <p>{labels[saved.outcome_status]}</p>
          {saved.outcome_evidence && (
            <AnalysisMarkdown>{saved.outcome_evidence}</AnalysisMarkdown>
          )}
        </div>
      )}
    </IssueProperty>
  );
}
