import { APP } from "./app-config";
/** Firebase identity adapter. Workspace membership stays in the application backend. */
import { getApps, initializeApp } from "firebase/app";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  sendPasswordResetEmail,
  sendEmailVerification,
} from "firebase/auth";
import {
  AuthConfigurationError,
  EmailVerificationRequiredError,
} from "./auth-errors";

function client() {
  const {
    VITE_GOOGLE_API_KEY: apiKey,
    VITE_GOOGLE_AUTH_DOMAIN: authDomain,
    VITE_GOOGLE_PROJECT_ID: projectId,
    VITE_GOOGLE_APP_ID: appId,
  } = import.meta.env;
  if (!apiKey || !authDomain || !projectId)
    throw new AuthConfigurationError(
      "Firebase configuration is incomplete. Set the public web settings for this application.",
    );
  const existing = getApps().find((app) => app.name === APP.id);
  if (existing && existing.options.projectId !== projectId)
    throw new AuthConfigurationError(
      "Firebase project configuration changed. Reload the application.",
    );
  return getAuth(
    existing ||
      initializeApp(
        { apiKey, authDomain, projectId, ...(appId ? { appId } : {}) },
        APP.id,
      ),
  );
}
function friendly(error: unknown): never {
  const code = (error as { code?: string })?.code;
  if (
    error instanceof EmailVerificationRequiredError ||
    error instanceof AuthConfigurationError
  )
    throw error;
  if (code === "auth/too-many-requests")
    throw new Error("Too many attempts. Please wait before trying again.");
  if (code === "auth/network-request-failed")
    throw new Error(
      "Cannot reach Firebase. Check your connection and try again.",
    );
  if (
    code === "auth/operation-not-allowed" ||
    code === "auth/configuration-not-found"
  )
    throw new AuthConfigurationError(
      "Email/password sign-in is not enabled for this Firebase project yet.",
    );
  if (
    code === "auth/weak-password" ||
    code === "auth/password-does-not-meet-requirements"
  )
    throw new Error("Choose a stronger password with at least 12 characters.");
  throw new Error(
    "Could not complete sign-in. Check your account details and try again.",
  );
}
export async function signIn(email: string, password: string) {
  try {
    const { user } = await signInWithEmailAndPassword(
      client(),
      email,
      password,
    );
    if (!user.emailVerified) throw new EmailVerificationRequiredError();
  } catch (error) {
    friendly(error);
  }
}
export async function createAccount(email: string, password: string) {
  if (password.length < 12)
    throw new Error("Choose a password with at least 12 characters.");
  try {
    await createUserWithEmailAndPassword(client(), email, password);
  } catch (error) {
    friendly(error);
  }
  // Account creation is a separate action from sending a verification email.
  throw new EmailVerificationRequiredError();
}
export async function signOut() {
  await firebaseSignOut(client());
}
export async function getToken() {
  const auth = client();
  await auth.authStateReady();
  return auth.currentUser?.emailVerified ? auth.currentUser.getIdToken() : null;
}
export async function resetPassword(email: string) {
  try {
    await sendPasswordResetEmail(client(), email);
  } catch (error) {
    // Keep the confirmation generic so reset does not reveal account existence.
    if (
      ["auth/user-not-found", "auth/invalid-email"].includes(
        (error as { code?: string }).code || "",
      )
    )
      return;
    friendly(error);
  }
}
export async function sendVerification() {
  const user = client().currentUser;
  if (!user) throw new Error("Sign in before requesting a verification email.");
  try {
    await sendEmailVerification(user);
  } catch (error) {
    friendly(error);
  }
}
export async function refreshVerification() {
  const user = client().currentUser;
  if (!user) throw new Error("Sign in again to continue.");
  await user.reload();
  if (!user.emailVerified) throw new EmailVerificationRequiredError();
  await user.getIdToken(true);
}
