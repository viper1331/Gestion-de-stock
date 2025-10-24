export function persistValue<T>(key: string, value: T) {
  localStorage.setItem(key, JSON.stringify(value));
}

export function readPersistedValue<T>(key: string, defaultValue: T): T {
  const raw = localStorage.getItem(key);
  if (!raw) return defaultValue;
  try {
    return JSON.parse(raw) as T;
  } catch (error) {
    return defaultValue;
  }
}
