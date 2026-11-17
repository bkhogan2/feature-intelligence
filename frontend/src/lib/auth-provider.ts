import { AuthConfigurationError } from "./auth-errors";

/** Hosting is independent of identity. New providers implement this contract. */
export interface AuthProvider {
  readonly id: string;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  getToken(): Promise<string | null>;
  resetPassword?(email: string): Promise<void>;
  createAccount?(email: string, password: string): Promise<void>;
  sendVerification?(): Promise<void>;
  refreshVerification?(): Promise<void>;
}
const firebaseProvider: AuthProvider = {
  id: "firebase",
  async signIn(email, password) {
    const google = await import("./google-auth");
    await google.signIn(email, password);
  },
  async signOut() {
    const google = await import("./google-auth");
    await google.signOut();
  },
  async getToken() {
    const google = await import("./google-auth");
    return google.getToken();
  },
  async resetPassword(email) {
    const google = await import("./google-auth");
    await google.resetPassword(email);
  },
  async createAccount(email, password) {
    const google = await import("./google-auth");
    await google.createAccount(email, password);
  },
  async sendVerification() {
    const google = await import("./google-auth");
    await google.sendVerification();
  },
  async refreshVerification() {
    const google = await import("./google-auth");
    await google.refreshVerification();
  },
};
const localProvider: AuthProvider = {
  id: "local",
  async signIn(email, password) {
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1/auth/login`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-App-Request": "1",
        },
        body: JSON.stringify({ email, password }),
      },
    );
    if (!response.ok)
      throw new Error(
        response.status === 429
          ? "Too many attempts. Try again in five minutes."
          : response.status >= 500
            ? "The backend is unavailable."
            : "Email or password is incorrect.",
      );
  },
  async signOut() {
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1/auth/logout`,
      {
        method: "POST",
        credentials: "include",
        headers: { "X-App-Request": "1" },
      },
    );
    if (!response.ok) throw new Error("Unable to sign out. Please retry.");
  },
  async getToken() {
    return null;
  },
};

/** Add adapters here without changing application screens or workspace permissions. */
export const authProviders: Readonly<Record<string, AuthProvider>> = {
  local: localProvider,
  firebase: firebaseProvider,
  google: firebaseProvider,
};
const configuredProvider = import.meta.env.VITE_AUTH_PROVIDER || "local";
const missing = async (): Promise<never> => {
  throw new AuthConfigurationError(
    `Unsupported authentication provider: ${configuredProvider}`,
  );
};
export const authProvider: AuthProvider = authProviders[configuredProvider] || {
  id: configuredProvider,
  signIn: missing,
  signOut: missing,
  getToken: missing,
};
