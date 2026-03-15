const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (!payload.exp) return false;
    return Date.now() / 1000 > payload.exp - 60;
  } catch {
    return true;
  }
}

async function fetchNewToken(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/auth/anonymous`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(`Auth failed: ${res.status}`);
  const data = await res.json();
  if (data.token) {
    localStorage.setItem("arsenal_token", data.token);
    localStorage.setItem("arsenal_user_id", data.user_id);
    return data.token;
  }
  throw new Error("No token received");
}

export async function ensureAuth(): Promise<string> {
  const token = localStorage.getItem("arsenal_token");
  if (token && !isTokenExpired(token)) return token;

  if (token) localStorage.removeItem("arsenal_token");
  return fetchNewToken();
}

export function clearAuth() {
  localStorage.removeItem("arsenal_token");
  localStorage.removeItem("arsenal_user_id");
}
