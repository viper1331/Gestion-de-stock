import { API_BASE_URL } from "./env";

const API_BASE_URL_WITH_SLASH = `${API_BASE_URL.replace(/\/$/, "")}/`;

export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    return new URL(url, API_BASE_URL_WITH_SLASH).toString();
  } catch (error) {
    return url;
  }
}
