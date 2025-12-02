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

const originalConsole: Record<LogLevel, (...args: unknown[]) => void> = {
  debug: console.debug.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
  log: console.log.bind(console)
};

let loggingInitialized = false;

function normalizeLevel(level: LogLevel): FrontendLogPayload["level"] {
  if (level === "warn") return "warning";
  if (level === "error") return "error";
  if (level === "debug") return "debug";
  if (level === "info") return "info";
  return "info";
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

  void sendLog({
    level: normalizeLevel(level),
    message,
    context,
    user_agent: typeof navigator !== "undefined" ? navigator.userAgent : undefined,
    url: typeof window !== "undefined" ? window.location.href : undefined,
    timestamp: new Date().toISOString()
  });
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
