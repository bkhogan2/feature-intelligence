import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
export function InvitationPanel({
  token,
  onDone,
}: {
  token: string;
  onDone: () => Promise<void>;
}) {
  const [invite, setInvite] = useState<{
    workspace_name: string;
    invited_email: string;
    terms_version: string;
    privacy_version: string;
  } | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api<typeof invite>("/onboarding/invitations/resolve", {
      method: "POST",
      body: JSON.stringify({ invitation_token: token }),
    })
      .then((i) => {
        if (alive) setInvite(i);
      })
      .catch(() => {
        if (alive) setError("This invitation is unavailable or expired.");
      });
    return () => {
      alive = false;
    };
  }, [token]);
  return (
    <div className="mx-auto max-w-md space-y-5 p-8">
      <h1 className="text-2xl font-semibold">Workspace invitation</h1>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {invite && (
        <>
          <p>
            Join {invite.workspace_name} as {invite.invited_email}.
          </p>
          <p className="text-xs text-muted-foreground">
            Terms: {invite.terms_version}. Privacy: {invite.privacy_version}.
          </p>
          <div className="flex items-start gap-3">
            <Checkbox
              id="accept-policies"
              checked={agreed}
              onCheckedChange={(v) => setAgreed(v === true)}
            />
            <Label htmlFor="accept-policies">
              I accept the{" "}
              <a
                className="underline"
                href={import.meta.env.VITE_TERMS_URL || "/terms.html"}
                target="_blank"
                rel="noreferrer"
              >
                terms
              </a>{" "}
              and{" "}
              <a
                className="underline"
                href={import.meta.env.VITE_PRIVACY_URL || "/privacy.html"}
                target="_blank"
                rel="noreferrer"
              >
                privacy policy
              </a>
              .
            </Label>
          </div>
          <Button
            disabled={!agreed || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api("/onboarding/invitations/accept", {
                  method: "POST",
                  body: JSON.stringify({
                    invitation_token: token,
                    accept_terms: true,
                    accept_privacy: true,
                  }),
                });
                await onDone();
              } catch {
                setError(
                  "Could not accept. Use the verified account matching the invitation email.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            Accept invitation
          </Button>
        </>
      )}
      <Button
        variant="ghost"
        onClick={() => {
          void onDone();
        }}
      >
        Back to workspaces
      </Button>
    </div>
  );
}
