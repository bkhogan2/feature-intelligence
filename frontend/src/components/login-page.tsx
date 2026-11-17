import { EmailVerificationRequiredError } from "@/lib/auth-errors";
import { authProvider } from "@/lib/auth-provider";
import { useState, type FormEvent } from "react";
import { Boxes, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Supply a real authentication adapter when using this starter in an application.
export function LoginPage({
  onSignIn,
  allowRegistration = false,
  onVerified,
}: {
  onSignIn: (email: string, password: string) => Promise<void>;
  allowRegistration?: boolean;
  onVerified?: () => Promise<void>;
}) {
  const [register, setRegister] = useState(false);
  const [needsVerification, setNeedsVerification] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (register && authProvider.createAccount)
        await authProvider.createAccount(email.trim(), password);
      else await onSignIn(email.trim(), password);
    } catch (error) {
      setNeedsVerification(error instanceof EmailVerificationRequiredError);
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setBusy(false);
      setPassword("");
    }
  }
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center gap-2 self-center text-sm font-medium tracking-tight">
          <div className="flex size-6 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Boxes className="size-4" aria-hidden />
          </div>
          <span>Feature Intelligence</span>
        </div>
        <Card>
          <CardHeader className="text-center">
            <CardTitle className="text-xl">
              {register ? "Create your account" : "Welcome back"}
            </CardTitle>
            <CardDescription>Sign in to your workspace.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  placeholder="name@example.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={busy}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <button
                    type="button"
                    className="text-xs font-medium text-primary hover:underline"
                    onClick={async () => {
                      if (!email) {
                        setMessage("Enter your email first.");
                        return;
                      }
                      if (!authProvider.resetPassword) {
                        setMessage(
                          "Contact your administrator to reset your password.",
                        );
                        return;
                      }
                      try {
                        await authProvider.resetPassword(email);
                        setMessage(
                          "Check your email for password reset instructions.",
                        );
                      } catch {
                        setMessage("Could not request a password reset.");
                      }
                    }}
                  >
                    Forgot password?
                  </button>
                </div>
                <div className="relative">
                  <Input
                    id="password"
                    type={visible ? "text" : "password"}
                    autoComplete={
                      register ? "new-password" : "current-password"
                    }
                    minLength={register ? 12 : undefined}
                    placeholder="Enter your password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={busy}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setVisible(!visible)}
                    aria-label={visible ? "Hide password" : "Show password"}
                    aria-pressed={visible}
                    className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-md text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    {visible ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
              </div>
              {message && (
                <p role="status" className="text-sm text-muted-foreground">
                  {message}
                </p>
              )}
              <Button
                type="submit"
                className="mt-1 w-full"
                disabled={busy || !email || !password}
              >
                {busy
                  ? "Please wait…"
                  : register
                    ? "Create account"
                    : "Sign in"}
              </Button>
            </form>
            {needsVerification && (
              <div className="mt-4 flex flex-col gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await authProvider.sendVerification?.();
                      setMessage(
                        "Verification email requested. Check your inbox.",
                      );
                    } catch (e) {
                      setMessage((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Send verification email
                </Button>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await authProvider.refreshVerification?.();
                      await onVerified?.();
                    } catch (e) {
                      setMessage((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  I've verified my email
                </Button>
              </div>
            )}
            {allowRegistration && authProvider.createAccount && (
              <Button
                type="button"
                variant="link"
                disabled={busy}
                className="mt-4 w-full"
                onClick={() => {
                  setRegister(!register);
                  setNeedsVerification(false);
                  setMessage("");
                }}
              >
                {register
                  ? "Already have an account? Sign in"
                  : "Invited? Create an account"}
              </Button>
            )}
            <p className="mt-6 text-center text-xs text-muted-foreground">
              Access is managed by your workspace administrator.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
