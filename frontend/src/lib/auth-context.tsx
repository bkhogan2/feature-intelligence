import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { authProvider } from "./auth-provider";
import { AuthConfigurationError } from "./auth-errors";
export type Membership = {
  workspace_slug: string;
  workspace_name: string;
  role: "admin" | "editor" | "viewer";
  theme_color: string;
};
type User = {
  subject: string;
  email: string;
  email_verified: boolean;
  platform_role?: "owner" | "admin" | null;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
let sessionGeneration = 0;
const sessionExpiredEvent = "app:session-expired";

export async function apiRequest(
  path: string,
  options: RequestInit = {},
  workspace?: string | null,
): Promise<Response> {
  const generation = sessionGeneration;
  const token = await authProvider.getToken();
  const headers = new Headers(options.headers);
  headers.set("X-App-Request", "1");
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (workspace) headers.set("X-Workspace", workspace);
  const response = await fetch(
    `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1${path}`,
    { ...options, headers, credentials: "include" },
  );
  if (response.status === 401 && generation === sessionGeneration) {
    window.dispatchEvent(new Event(sessionExpiredEvent));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(
      response.status,
      detail || `Request failed (${response.status})`,
    );
  }
  return response;
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
  workspace?: string | null,
): Promise<T> {
  const response = await apiRequest(path, options, workspace);
  return response.status === 204 ? (undefined as T) : response.json();
}
type Context = {
  user: User | null;
  memberships: Membership[];
  active: Membership | null;
  status: "loading" | "ready" | "error";
  error: string;
  refresh: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  selectWorkspace: (slug: string) => void;
};
const AuthContext = createContext<Context | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [selected, setSelected] = useState("");
  const [status, setStatus] = useState<Context["status"]>("loading");
  const [error, setError] = useState("");
  const version = useRef(0);
  const refresh = useCallback(async (requireAuthentication = false) => {
    const attempt = ++version.current;
    try {
      const config = await api<{ provider: string; projectId?: string }>(
        "/auth/config",
      );
      if (config.provider !== authProvider.id)
        throw new AuthConfigurationError(
          "Frontend and backend authentication providers do not match.",
        );
      if (
        config.provider === "firebase" &&
        config.projectId !== import.meta.env.VITE_GOOGLE_PROJECT_ID
      )
        throw new AuthConfigurationError(
          "Frontend and backend Firebase projects do not match.",
        );
      const [current, list] = await Promise.all([
        api<User>("/me"),
        api<Membership[]>("/me/workspaces"),
      ]);
      if (attempt !== version.current) return;
      setUser(current);
      setMemberships(list);
      setSelected((value) =>
        list.some((m) => m.workspace_slug === value)
          ? value
          : list.length === 1
            ? list[0].workspace_slug
            : "",
      );
      setStatus("ready");
      setError("");
    } catch (e) {
      if (attempt !== version.current) return;
      setUser(null);
      setMemberships([]);
      setSelected("");
      if (e instanceof ApiError && e.status === 401) {
        setStatus("ready");
        setError("");
      } else {
        setStatus("error");
        setError(
          e instanceof AuthConfigurationError
            ? e.message
            : "Cannot reach the application backend. Check that it is running.",
        );
      }
      if (requireAuthentication) throw e;
    }
  }, []);
  useEffect(() => {
    const expire = () => {
      sessionGeneration++;
      version.current++;
      setUser(null);
      setMemberships([]);
      setSelected("");
      setError("");
      setStatus("ready");
    };
    window.addEventListener(sessionExpiredEvent, expire);
    return () => window.removeEventListener(sessionExpiredEvent, expire);
  }, []);
  useEffect(() => {
    void refresh();
    return () => {
      version.current++;
    };
  }, [refresh]);
  async function signIn(email: string, password: string) {
    sessionGeneration++;
    await authProvider.signIn(email, password);
    await refresh(true);
  }
  async function signOut() {
    await authProvider.signOut();
    sessionGeneration++;
    version.current++;
    setUser(null);
    setMemberships([]);
    setSelected("");
    window.location.hash = "login";
  }
  const active = memberships.find((m) => m.workspace_slug === selected) ?? null;
  return (
    <AuthContext.Provider
      value={{
        user,
        memberships,
        active,
        status,
        error,
        refresh,
        signIn,
        signOut,
        selectWorkspace: (slug) => {
          if (memberships.some((m) => m.workspace_slug === slug))
            setSelected(slug);
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is missing");
  return context;
}
