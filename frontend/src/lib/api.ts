// Thin client for the FastAPI REST API (proxied same-origin under /api/v1).
// Cookies are httpOnly; the only cookie scripts can read is the CSRF token, which is echoed in a header.

export const API = "/api/v1";

export class ApiError extends Error {
  status: number;
  code?: string;
  fields: Record<string, string>;
  detail: Record<string, unknown>;
  constructor(status: number, detail: Record<string, unknown>) {
    super(String(detail.message ?? `Request failed (${status})`));
    this.status = status;
    this.code = detail.code as string | undefined;
    this.fields = (detail.fields as Record<string, string>) ?? (detail.field ? { [String(detail.field)]: this.message } : {});
    this.detail = detail;
  }
}

function csrf(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function qs(params?: Query): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${API}/auth/refresh`, { method: "POST", headers: { "X-CSRF-Token": csrf() } })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => setTimeout(() => (refreshing = null), 0));
  }
  return refreshing;
}

export type SessionListener = (reason: string) => void;
let onSessionLost: SessionListener = () => {};
export function setSessionListener(fn: SessionListener) {
  onSessionLost = fn;
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") headers["X-CSRF-Token"] = csrf();
  const res = await fetch(`${API}${path}`, { method, headers, body: payload, credentials: "same-origin" });
  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
    const data = await res.clone().json().catch(() => ({}));
    if (data?.detail?.code !== "session_expired" && (await tryRefresh())) return request<T>(method, path, body, false);
    onSessionLost(data?.detail?.code ?? "unauthenticated");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? { message: data.detail } : data.detail ?? {};
    if (res.status === 403 && detail.code === "password_change_required" && typeof window !== "undefined") {
      window.location.href = "/change-password";
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export const api = {
  get: <T = any>(path: string, params?: Query) => request<T>("GET", path + qs(params)),
  post: <T = any>(path: string, body?: unknown, params?: Query) => request<T>("POST", path + qs(params), body),
  patch: <T = any>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T = any>(path: string, body?: unknown) => request<T>("PUT", path, body),
};

/** Open a server-generated file (PDF, CSV, Excel) — same-origin, so the session cookie is sent. */
export function openFile(path: string, params?: Query) {
  window.open(`${API}${path}${qs(params)}`, "_blank", "noopener");
}

/** Download a file produced by a POST (e.g. backup) through fetch, keeping the CSRF header. */
export async function downloadPost(path: string, filename: string) {
  const res = await fetch(`${API}${path}`, { method: "POST", headers: { "X-CSRF-Token": csrf() } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(res.status, data.detail ?? {});
  }
  const disp = res.headers.get("content-disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disp)?.[1] ?? filename;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
