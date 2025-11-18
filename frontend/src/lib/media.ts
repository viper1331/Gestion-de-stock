import { getCachedApiBaseUrl } from "./apiConfig";

export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    const base = `${getCachedApiBaseUrl()}/`;
    return new URL(url, base).toString();
  } catch (error) {
    return url;
  }
}
