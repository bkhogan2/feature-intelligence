import { useState, useRef, type FormEvent } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

type Feedback = {
  id: string;
  title: string;
  description: string;
  submitted_by: string;
  created_at: string;
};

export function FeedbackPanel({
  workspace,
  role,
}: {
  workspace: string;
  role: string;
}) {
  const submissionKey = useRef(crypto.randomUUID());
  const [savedId, setSavedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [saved, setSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = role === "admin" || role === "editor";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !title.trim() || !description.trim()) return;
    setSubmitting(true);
    setSubmitError("");
    setSaved(false);
    try {
      const created = await api<Feedback>(
        "/feedback",
        {
          method: "POST",
          body: JSON.stringify({
            submission_key: submissionKey.current,
            title: title.trim(),
            description: description.trim(),
          }),
        },
        workspace,
      );
      submissionKey.current = crypto.randomUUID();
      setSavedId(created.id);
      setTitle("");
      setDescription("");
      setSaved(true);
      window.dispatchEvent(new Event("updates-changed"));
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Feedback</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Capture requests and the problems behind them for your workspace.
        </p>
      </div>
      {canSubmit ? (
        <form onSubmit={submit} className="space-y-4 rounded-xl border p-5">
          <h2 className="font-semibold">Share feedback</h2>
          <div className="space-y-2">
            <Label htmlFor="feedback-title">Title</Label>
            <Input
              id="feedback-title"
              value={title}
              onChange={(e) => {
                submissionKey.current = crypto.randomUUID();
                setTitle(e.target.value);
              }}
              maxLength={160}
              required
              disabled={submitting}
              placeholder="A short summary of the request"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="feedback-description">Description</Label>
            <Textarea
              id="feedback-description"
              value={description}
              onChange={(e) => {
                submissionKey.current = crypto.randomUUID();
                setDescription(e.target.value);
              }}
              maxLength={10000}
              required
              disabled={submitting}
              rows={5}
              aria-describedby="feedback-description-help"
              placeholder="What is difficult today? Who is affected, and what would improve their experience?"
            />
            <p
              id="feedback-description-help"
              className="text-xs text-muted-foreground"
            >
              Describe the problem, context, or suggested improvement. Up to
              10,000 characters.
            </p>
          </div>
          <Button disabled={submitting || !title.trim() || !description.trim()}>
            {submitting ? "Submitting…" : "Submit feedback"}
          </Button>
          {submitError && (
            <p role="alert" className="text-sm text-destructive">
              Could not submit feedback: {submitError}. Your draft is still
              here.
            </p>
          )}
        </form>
      ) : (
        <p className="text-sm text-muted-foreground">
          You have read-only access. Admins and editors can submit feedback.
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          Feedback submitted.{" "}
          {savedId && (
            <a className="underline" href={`#inbox?status=all&id=${savedId}`}>
              View request and analysis status
            </a>
          )}
        </p>
      )}
    </div>
  );
}
