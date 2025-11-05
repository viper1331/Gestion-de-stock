const DEFAULT_API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const API_BASE_URL = DEFAULT_API_URL.endsWith("/") ? DEFAULT_API_URL : `${DEFAULT_API_URL}/`;

export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    return new URL(url, API_BASE_URL).toString();
  } catch (error) {
    return url;
  }
}
