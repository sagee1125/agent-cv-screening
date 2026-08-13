import { apiGet, apiPost } from "../services/api";

export function get<T>(path: string): Promise<T> {
  return apiGet<T>(path);
}

export function post<T>(path: string, body?: BodyInit | null): Promise<T> {
  let payload: unknown = body;
  if (typeof body === "string") {
    try {
      payload = JSON.parse(body);
    } catch {
      payload = body;
    }
  }
  return apiPost<T>(path, payload);
}
