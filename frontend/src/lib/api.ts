import axios, { AxiosError, AxiosHeaders, AxiosRequestConfig } from "axios";

import { API_BASE_URL } from "./env";
import { resetApiConfigCache, resolveApiBaseUrl } from "./apiConfig";
import { apiDebug } from "./debug";
import { emitAuthLogout } from "../features/auth/authEvents";
import {
  clearStoredRefreshToken,
  getRefreshTokenStorage,
  getStoredRefreshToken,
  storeRefreshToken
} from "../features/auth/authStorage";

const DEFAULT_BASE_URL = API_BASE_URL.replace(/\/$/, "");

export const api = axios.create({
  baseURL: DEFAULT_BASE_URL,
  withCredentials: true
});

let adminSiteOverride: string | null = null;

export function setAdminSiteOverride(siteKey: string | null) {
  adminSiteOverride = siteKey;
}

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
  if (adminSiteOverride) {
    const headers = AxiosHeaders.from(config.headers ?? {});
    headers.set("X-Site-Key", adminSiteOverride);
    config.headers = headers;
  }
  apiDebug("Request", {
    url: config.url,
    method: config.method,
    params: config.params,
    hasBody: Boolean(config.data)
  });
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

interface RetriableRequestConfig extends AxiosRequestConfig {
  _retry?: boolean;
}

export async function handleApiError(error: unknown): Promise<unknown> {
  const originalRequest = (error as AxiosError).config as RetriableRequestConfig | undefined;
  const isUnauthorized = (error as AxiosError).response?.status === 401;
  apiDebug("Response error", {
    url: originalRequest?.url,
    status: (error as AxiosError).response?.status,
    message: (error as AxiosError).message
  });
  const storedRefresh = getStoredRefreshToken();
  const refreshStorage = getRefreshTokenStorage();

  if (isUnauthorized && storedRefresh && originalRequest && !originalRequest._retry) {
    try {
      originalRequest._retry = true;
      const baseURL = await ensureBaseUrl();
      const refreshClient = axios.create({ baseURL });
      const { data } = await refreshClient.post("/auth/refresh", { refresh_token: storedRefresh });

      if (refreshStorage) {
        storeRefreshToken(data.refresh_token, refreshStorage);
      }
      setAccessToken(data.access_token);
      originalRequest.headers = {
        ...originalRequest.headers,
        Authorization: `Bearer ${data.access_token}`
      };

      return api(originalRequest);
    } catch (refreshError) {
      clearStoredRefreshToken();
      setAccessToken(null);
      emitAuthLogout("unauthorized");
      return Promise.reject(refreshError);
    }
  }

  if (isUnauthorized) {
    clearStoredRefreshToken();
    setAccessToken(null);
    emitAuthLogout("unauthorized");
  }

  return Promise.reject(error);
}

api.interceptors.response.use(
  (response) => {
    apiDebug("Response", {
      url: response.config.url,
      status: response.status,
      method: response.config.method
    });
    return response;
  },
  handleApiError
);
