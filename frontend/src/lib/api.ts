import axios from "axios";

import { API_BASE_URL } from "./env";

export const api = axios.create({
  baseURL: API_BASE_URL.replace(/\/$/, "")
});

export function setAccessToken(token: string | null) {
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common.Authorization;
  }
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
