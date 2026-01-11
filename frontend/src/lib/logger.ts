import { api } from "./api";

export type LogLevel = "debug" | "info" | "warn" | "error" | "log";

interface FrontendLogPayload {
  level: "debug" | "info" | "warning" | "error" | "critical";
  message: string;
  context?: Record<string, unknown>;
  user_agent?: string;
  url?: string;
  timestamp?: string;
}

interface StoredLogEntry extends FrontendLogPayload {
  timestamp: string;
}

const originalConsole: Record<LogLevel, (...args: unknown[]) => void> = {
  debug: console.debug.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
  log: console.log.bind(console)
};

const LOG_STORAGE_KEY = "frontend-logs";
const LOG_SETTINGS_KEY = "frontend-log-settings";
const LOG_MAX_BYTES = 3_072_000;
const LOG_MAX_ENTRIES = 3000;

let loggingInitialized = false;

function normalizeLevel(level: LogLevel): FrontendLogPayload["level"] {
  if (level === "warn") return "warning";
  if (level === "error") return "error";
  if (level === "debug") return "debug";
  if (level === "info") return "info";
  return "info";
}

function canAccessStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readSettings(): { persist: boolean } {
  if (!canAccessStorage()) {
    return { persist: false };
  }
  const stored = window.localStorage.getItem(LOG_SETTINGS_KEY);
  if (!stored) {
    return { persist: false };
  }
  try {
    const parsed = JSON.parse(stored) as { persist?: boolean };
    return { persist: Boolean(parsed.persist) };
  } catch {
    return { persist: false };
  }
}

export function isLogPersistenceEnabled() {
  return readSettings().persist;
}

export function setLogPersistenceEnabled(enabled: boolean) {
  if (!canAccessStorage()) {
    return;
  }
  window.localStorage.setItem(LOG_SETTINGS_KEY, JSON.stringify({ persist: enabled }));
}

function readPersistedLogs(): StoredLogEntry[] {
  if (!canAccessStorage()) {
    return [];
  }
  const stored = window.localStorage.getItem(LOG_STORAGE_KEY);
  if (!stored) {
    return [];
  }
  try {
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? (parsed as StoredLogEntry[]) : [];
  } catch {
    return [];
  }
}

function writePersistedLogs(entries: StoredLogEntry[]) {
  if (!canAccessStorage()) {
    return;
  }
  window.localStorage.setItem(LOG_STORAGE_KEY, JSON.stringify(entries));
}

function trimPersistedLogs(entries: StoredLogEntry[]) {
  let trimmed = [...entries];
  while (trimmed.length > LOG_MAX_ENTRIES) {
    trimmed.shift();
  }
  if (!canAccessStorage()) {
    return trimmed;
  }
  const encoder = new TextEncoder();
  let encoded = encoder.encode(JSON.stringify(trimmed));
  while (encoded.byteLength > LOG_MAX_BYTES && trimmed.length > 0) {
    trimmed.shift();
    encoded = encoder.encode(JSON.stringify(trimmed));
  }
  return trimmed;
}

function persistLogEntry(payload: FrontendLogPayload) {
  if (!isLogPersistenceEnabled()) {
    return;
  }
  const entry: StoredLogEntry = {
    ...payload,
    timestamp: payload.timestamp ?? new Date().toISOString()
  };
  const entries = trimPersistedLogs([...readPersistedLogs(), entry]);
  writePersistedLogs(entries);
}

export function enforcePersistedLogsLimit() {
  const entries = readPersistedLogs();
  if (entries.length === 0) {
    return;
  }
  const trimmed = trimPersistedLogs(entries);
  if (trimmed.length !== entries.length) {
    writePersistedLogs(trimmed);
  }
}

export function clearPersistedLogs() {
  if (!canAccessStorage()) {
    return;
  }
  window.localStorage.removeItem(LOG_STORAGE_KEY);
}

export function getPersistedLogs() {
  return readPersistedLogs();
}

async function sendLog(payload: FrontendLogPayload) {
  try {
    const normalizedBaseUrl = api.defaults.baseURL?.replace(/\/$/, "") ?? "";
    const endpoint = `${normalizedBaseUrl}/logs/frontend`;
    const body = JSON.stringify(payload);

    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(endpoint, blob);
      return;
    }

    await api.post("/logs/frontend", payload, { timeout: 2000 });
  } catch (error) {
    originalConsole.warn("Echec d'envoi du log frontend", error);
  }
}

export function logEvent(level: LogLevel, message: string, context?: Record<string, unknown>) {
  const targetConsole = originalConsole[level] ?? originalConsole.log;
  targetConsole(message, context);

  const payload: FrontendLogPayload = {
    level: normalizeLevel(level),
    message,
    context,
    user_agent: typeof navigator !== "undefined" ? navigator.userAgent : undefined,
    url: typeof window !== "undefined" ? window.location.href : undefined,
    timestamp: new Date().toISOString()
  };

  persistLogEntry(payload);
  void sendLog(payload);
}

function forwardConsole(level: LogLevel) {
  console[level] = (...args: unknown[]) => {
    const message = args
      .map((arg) => {
        if (typeof arg === "string") return arg;
        try {
          return JSON.stringify(arg);
        } catch {
          return String(arg);
        }
      })
      .join(" ");
    logEvent(level, message);
  };
}

export function initializeLogging() {
  if (loggingInitialized) return;
  loggingInitialized = true;
  enforcePersistedLogsLimit();

  forwardConsole("log");
  forwardConsole("info");
  forwardConsole("warn");
  forwardConsole("error");
  forwardConsole("debug");

  window.addEventListener("error", (event) => {
    logEvent("error", event.message, {
      source: event.filename,
      line: event.lineno,
      column: event.colno
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    logEvent("error", "Unhandled rejection", {
      reason: event.reason instanceof Error ? event.reason.message : String(event.reason)
    });
  });

  window.addEventListener("online", () => logEvent("info", "Navigateur en ligne"));
  window.addEventListener("offline", () => logEvent("warn", "Navigateur hors ligne"));
  document.addEventListener("visibilitychange", () =>
    logEvent("info", "Changement de visibilité", { state: document.visibilityState })
  );
}
