import { Dispatch, SetStateAction, useEffect, useState } from "react";

function readStoredBoolean(key: string, fallback: boolean): boolean {
  if (typeof window === "undefined") {
    return fallback;
  }

  try {
    const storedValue = window.localStorage.getItem(key);
    if (storedValue === null) {
      return fallback;
    }

    const parsedValue = JSON.parse(storedValue);
    if (typeof parsedValue === "boolean") {
      return parsedValue;
    }

    return parsedValue === "true" ? true : parsedValue === "false" ? false : fallback;
  } catch (error) {
    console.warn("Impossible de lire l'état persistant de la section", error);
    return fallback;
  }
}

export function usePersistentBoolean(
  key: string,
  initialValue: boolean
): [boolean, Dispatch<SetStateAction<boolean>>] {
  const [value, setValue] = useState<boolean>(() => readStoredBoolean(key, initialValue));

  useEffect(() => {
    setValue(readStoredBoolean(key, initialValue));
  }, [key, initialValue]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      console.warn("Impossible d'enregistrer l'état persistant de la section", error);
    }
  }, [key, value]);

  return [value, setValue];
}
