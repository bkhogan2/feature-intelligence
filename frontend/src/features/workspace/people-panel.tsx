import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
type Member = {
  membership_id: string;
  email: string;
  role: string;
  status: string;
  is_current_user: boolean;
};
export function PeoplePanel({ workspace }: { workspace: string }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<
    {
      invitation_id: string;
      invited_email: string;
      role: string;
      status: string;
    }[]
  >([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const [m, i] = await Promise.all([
      api<Member[]>("/workspace/members", {}, workspace),
      api<typeof invitations>("/workspace/invitations", {}, workspace),
    ]);
    setMembers(m);
    setInvitations(i);
  }
  useEffect(() => {
    let alive = true;
    Promise.all([
      api<Member[]>("/workspace/members", {}, workspace),
      api<typeof invitations>("/workspace/invitations", {}, workspace),
    ])
      .then(([m, i]) => {
        if (alive) {
          setMembers(m);
          setInvitations(i);
        }
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [workspace]);
  async function mutate(work: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await work();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">People & invitations</h2>
      <p className="text-sm text-muted-foreground">
        Administrators manage access. Editors can change data; viewers can read
        it.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <ul className="divide-y rounded-lg border">
        {members.map((m) => (
          <li
            key={m.membership_id}
            className="flex flex-wrap items-center gap-3 p-3"
          >
            <span className="min-w-0 flex-1 break-words text-sm">
              {m.email}
              {m.is_current_user ? " (you)" : ""}
            </span>
            <select
              aria-label={`Role for ${m.email}`}
              value={m.role}
              disabled={busy}
              className="rounded-md border bg-background p-2 text-sm"
              onChange={(e) => {
                void mutate(() =>
                  api(
                    `/workspace/members/${m.membership_id}`,
                    {
                      method: "PATCH",
                      body: JSON.stringify({ role: e.target.value }),
                    },
                    workspace,
                  ),
                );
              }}
            >
              {["admin", "editor", "viewer"].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => {
                void mutate(() =>
                  api(
                    `/workspace/members/${m.membership_id}`,
                    {
                      method: "PATCH",
                      body: JSON.stringify({
                        status: m.status === "active" ? "disabled" : "active",
                      }),
                    },
                    workspace,
                  ),
                );
              }}
            >
              {m.status === "active" ? "Disable" : "Enable"}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void mutate(async () => {
            const created = await api<{ invitation_token: string }>(
              "/workspace/invitations",
              {
                method: "POST",
                body: JSON.stringify({ invited_email: email, role }),
              },
              workspace,
            );
            setLink(
              `${location.origin}${location.pathname}#invite=${encodeURIComponent(created.invitation_token)}`,
            );
            setEmail("");
          });
        }}
      >
        <Input
          type="email"
          aria-label="Invitation email"
          placeholder="name@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="min-w-0 flex-1"
          required
        />
        <select
          aria-label="Invitation role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-md border bg-background p-2 text-sm"
        >
          {["viewer", "editor", "admin"].map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <Button disabled={busy}>Create invite link</Button>
      </form>
      {link && (
        <div className="space-y-2 rounded-lg border p-3">
          <Label htmlFor="invite-link">Invitation link</Label>
          <Input
            id="invite-link"
            value={link}
            readOnly
            onFocus={(e) => e.target.select()}
          />
          <p className="text-xs text-muted-foreground">
            Share this link with the invited person. No email has been sent.
          </p>
        </div>
      )}
      <ul className="space-y-2">
        {invitations.map((i) => (
          <li
            key={i.invitation_id}
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <span className="min-w-0 flex-1 break-words">
              {i.invited_email} · {i.role} · {i.status}
            </span>
            {i.status === "pending" && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  void mutate(() =>
                    api(
                      `/workspace/invitations/${i.invitation_id}`,
                      { method: "DELETE" },
                      workspace,
                    ),
                  );
                }}
              >
                Revoke
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
