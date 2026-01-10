import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { SpellcheckLanguage } from "../lib/spellcheck";

export interface SpellcheckSettings {
  enabled: boolean;
  language: SpellcheckLanguage;
  live: boolean;
}

const SETTINGS_KEY = "gsp/spellcheck/settings";

const DEFAULT_SETTINGS: SpellcheckSettings = {
  enabled: true,
  language: "fr",
  live: false
};

interface SpellcheckSettingsContextValue {
  settings: SpellcheckSettings;
  updateSettings: (next: Partial<SpellcheckSettings>) => void;
}

const SpellcheckSettingsContext = createContext<SpellcheckSettingsContextValue | undefined>(
  undefined
);

function readSettings(): SpellcheckSettings {
  if (typeof window === "undefined") {
    return DEFAULT_SETTINGS;
  }

  try {
    const stored = window.localStorage.getItem(SETTINGS_KEY);
    if (!stored) {
      return DEFAULT_SETTINGS;
    }
    const parsed = JSON.parse(stored) as Partial<SpellcheckSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch (error) {
    console.warn("Impossible de lire les préférences du correcteur", error);
    return DEFAULT_SETTINGS;
  }
}

export function SpellcheckSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SpellcheckSettings>(() => readSettings());

  useEffect(() => {
    setSettings(readSettings());
  }, []);

  const updateSettings = useCallback((next: Partial<SpellcheckSettings>) => {
    setSettings((prev) => {
      const updated = { ...prev, ...next };
      if (typeof window !== "undefined") {
        try {
          window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(updated));
        } catch (error) {
          console.warn("Impossible d'enregistrer les préférences du correcteur", error);
        }
      }
      return updated;
    });
  }, []);

  const value = useMemo(() => ({ settings, updateSettings }), [settings, updateSettings]);

  return (
    <SpellcheckSettingsContext.Provider value={value}>
      {children}
    </SpellcheckSettingsContext.Provider>
  );
}

export function useSpellcheckSettings() {
  const context = useContext(SpellcheckSettingsContext);
  if (!context) {
    throw new Error("useSpellcheckSettings must be used within SpellcheckSettingsProvider");
  }
  return context;
}
