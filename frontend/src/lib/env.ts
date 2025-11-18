const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() ||
  "http://localhost:8000";

export { API_BASE_URL };
