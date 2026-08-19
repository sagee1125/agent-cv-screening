// Thin fetch wrappers for JSON and FormData REST calls.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

type QueryParams = Record<string, string | number | undefined>;

/** Builds an absolute API URL with optional query parameters. */
function buildUrl(path: string, params?: QueryParams): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${API_BASE_URL}${normalizedPath}`);
  if (!params) return url.toString();

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

/** Sends an HTTP request and returns parsed JSON, or throws on non-OK status. */
async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  params?: QueryParams
): Promise<T> {
  const headers = new Headers();
  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (body instanceof FormData) {
      requestBody = body;
    } else if (typeof body === "string") {
      headers.set("Content-Type", "application/json");
      requestBody = body;
    } else {
      headers.set("Content-Type", "application/json");
      requestBody = JSON.stringify(body);
    }
  }

  const response = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: requestBody,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const errorBody = (await response.json()) as {
        error?: string;
        detail?: string;
        message?: string;
      };
      message =
        errorBody.error ?? errorBody.detail ?? errorBody.message ?? message;
    } catch {
      // ignore json parse errors
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Performs a GET request against the API. */
export function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  return request<T>("GET", path, undefined, params);
}

/** Performs a POST request against the API. */
export function apiPost<T>(
  path: string,
  body?: unknown,
  params?: QueryParams
): Promise<T> {
  return request<T>("POST", path, body, params);
}

/** Performs a PUT request against the API. */
export function apiPut<T>(
  path: string,
  body?: unknown,
  params?: QueryParams
): Promise<T> {
  return request<T>("PUT", path, body, params);
}

/** Performs a PATCH request against the API. */
export function apiPatch<T>(
  path: string,
  body?: unknown,
  params?: QueryParams
): Promise<T> {
  return request<T>("PATCH", path, body, params);
}

/** Performs a DELETE request against the API. */
export function apiDelete<T>(path: string, params?: QueryParams): Promise<T> {
  return request<T>("DELETE", path, undefined, params);
}
