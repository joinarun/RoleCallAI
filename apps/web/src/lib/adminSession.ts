import { api } from "./api";

const CSRF_KEY = "rolecall.admin.csrf";

export function setCsrfToken(token: string) {
  sessionStorage.setItem(CSRF_KEY, token);
}

export function clearCsrfToken() {
  sessionStorage.removeItem(CSRF_KEY);
}

export function csrfToken() {
  return sessionStorage.getItem(CSRF_KEY) ?? "";
}

export function adminApi<T>(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const token = csrfToken();
  if (token) headers.set("X-CSRF-Token", token);
  return api<T>(path, { ...init, headers });
}
