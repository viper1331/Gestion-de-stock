import axios from "axios";

import { API_BASE_URL } from "./env";
import { resetApiConfigCache, resolveApiBaseUrl } from "./apiConfig";

const DEFAULT_BASE_URL = API_BASE_URL.replace(/\/$/, "");

export const api = axios.create({
  baseURL: DEFAULT_BASE_URL
});

async function ensureBaseUrl(): Promise<string> {
  try {
    const { baseUrl } = await resolveApiBaseUrl();
    const normalized = baseUrl.replace(/\/$/, "");
    api.defaults.baseURL = normalized;
    return normalized;
  } catch {
    api.defaults.baseURL = DEFAULT_BASE_URL;
    return DEFAULT_BASE_URL;
  }
}

api.interceptors.request.use(async (config) => {
  const baseUrl = await ensureBaseUrl();
  config.baseURL = baseUrl;
  return config;
});

export function setAccessToken(token: string | null) {
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common.Authorization;
  }
}

export async function refreshApiBaseUrl() {
  resetApiConfigCache();
  await ensureBaseUrl();
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("gsp/token");
      setAccessToken(null);
    }
    return Promise.reject(error);
  }
);
