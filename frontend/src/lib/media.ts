import { getApiBaseUrl } from "./env";

const API_BASE_URL = `${getApiBaseUrl()}/`;

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
