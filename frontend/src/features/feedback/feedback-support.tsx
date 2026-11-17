import { useEffect, useRef, useState } from "react";
import { Button as PrimerButton } from "@primer/react";
import { ThumbsupIcon } from "@primer/octicons-react";
import { ThumbsUp } from "lucide-react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";

export type FeedbackSupport = {
  support_count: number;
  supported_by_me: boolean;
};

export function FeedbackSupportButton({
  requestId,
  workspace,
  support,
  onChange,
  compact = false,
}: {
  compact?: boolean;
  requestId: string;
  workspace: string;
  support: FeedbackSupport;
  onChange: (support: FeedbackSupport) => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function toggle() {
    if (controller.current) return;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError("");
    setAnnouncement("");
    try {
      const saved = await api<FeedbackSupport>(
        `/feedback/${requestId}/support`,
        {
          method: support.supported_by_me ? "DELETE" : "POST",
          signal: request.signal,
        },
        workspace,
      );
      if (request.signal.aborted) return;
      onChange(saved);
      setAnnouncement(
        saved.supported_by_me
          ? "Your support was added."
          : "Your support was removed.",
      );
    } catch (err) {
      if (!request.signal.aborted)
        setError(
          `Could not update support: ${(err as Error).message}. Try again or refresh to check the saved state.`,
        );
    } finally {
      if (!request.signal.aborted) {
        controller.current = null;
        setPending(false);
      }
    }
  }
  if (compact)
    return (
      <div>
        <PrimerButton
          size="small"
          variant="invisible"
          leadingVisual={ThumbsupIcon}
          aria-label={
            support.supported_by_me
              ? "Remove your support"
              : "Support this request"
          }
          aria-pressed={support.supported_by_me}
          disabled={pending}
          onClick={() => void toggle()}
        >
          {support.support_count}
        </PrimerButton>
        <span role="status" className="sr-only">
          {announcement}
        </span>
        {error && <p role="alert">{error}</p>}
      </div>
    );
  return (
    <div className="mt-5 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={support.supported_by_me ? "secondary" : "outline"}
          size="sm"
          aria-pressed={support.supported_by_me}
          aria-label={
            support.supported_by_me
              ? "Remove your support"
              : "Support this request"
          }
          disabled={pending}
          onClick={() => void toggle()}
        >
          <ThumbsUp className="size-4" aria-hidden />
          {pending
            ? "Saving…"
            : support.supported_by_me
              ? "Supported"
              : "Support"}
        </Button>
        <span className="text-xs text-muted-foreground">
          {support.support_count}{" "}
          {support.support_count === 1 ? "supporter" : "supporters"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Support signals interest. It does not set priority or approve triage.
      </p>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
