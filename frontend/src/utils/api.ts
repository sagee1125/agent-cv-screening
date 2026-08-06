import { ApiErrorBody } from "./types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function get<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, method: "GET" });
}

export function post<T>(
  path: string,
  body?: BodyInit | null,
  init?: RequestInit
): Promise<T> {
  return request<T>(path, { ...init, method: "POST", body });
}

/***********************************************/

function buildUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const errorBody = (await response.json()) as ApiErrorBody;
    return (
      errorBody.error ?? errorBody.detail ?? `请求失败: ${response.status}`
    );
  } catch {
    return `请求失败: ${response.status}`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), init);
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }
  return (await response.json()) as T;
}
