import { registerAnonymous } from "./api";

/**
 * Ensure we have a valid auth token.
 * Auto-registers anonymous user if no token exists.
 */
export async function ensureAuth(): Promise<string> {
  let token = localStorage.getItem("arsenal_token");
  if (token) return token;

  const data = await registerAnonymous();
  token = data.token;
  if (token) {
    localStorage.setItem("arsenal_token", token);
    localStorage.setItem("arsenal_user_id", data.user_id);
    return token;
  }
  throw new Error("No token received");
}
