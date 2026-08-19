// Compatibility wrappers around the REST client used by older modules.
import { apiGet, apiPost } from "../services/api";

/** Performs a GET request via the shared API client. */
export function get<T>(path: string): Promise<T> {
  return apiGet<T>(path);
}

/** Performs a POST request, parsing JSON string bodies when possible. */
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
