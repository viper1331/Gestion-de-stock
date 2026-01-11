import nspell from "nspell";

export type SpellcheckLanguage = "fr" | "en";

export interface SpellcheckError {
  start: number;
  end: number;
  word: string;
  suggestions: string[];
}

interface DictionaryData {
  aff: string;
  dic: string;
}

interface Spellchecker {
  correct(word: string): boolean;
  suggest(word: string): string[];
}

const USER_DICTIONARY_KEY = "gsp/spellcheck/user-dictionary";
const dictionaryCache = new Map<SpellcheckLanguage, Promise<DictionaryData>>();
const spellcheckerCache = new Map<SpellcheckLanguage, Promise<Spellchecker>>();

const WORD_REGEX = /[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*/g;

function loadDictionary(language: SpellcheckLanguage): Promise<DictionaryData> {
  if (!dictionaryCache.has(language)) {
    const loadPromise = new Promise<DictionaryData>((resolve, reject) => {
      if (language === "fr") {
        import("dictionary-fr")
          .then((mod) => {
            mod.default((error: Error | null, dict: DictionaryData) => {
              if (error) {
                reject(error);
                return;
              }
              resolve(dict);
            });
          })
          .catch(reject);
        return;
      }

      import("dictionary-en")
        .then((mod) => {
          mod.default((error: Error | null, dict: DictionaryData) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(dict);
          });
        })
        .catch(reject);
    });

    dictionaryCache.set(language, loadPromise);
  }

  return dictionaryCache.get(language) as Promise<DictionaryData>;
}

async function getSpellchecker(language: SpellcheckLanguage): Promise<Spellchecker> {
  if (!spellcheckerCache.has(language)) {
    spellcheckerCache.set(
      language,
      (async () => {
        const dict = await loadDictionary(language);
        return nspell(dict);
      })()
    );
  }

  return spellcheckerCache.get(language) as Promise<Spellchecker>;
}

function normalizeWord(word: string) {
  return word.trim().toLowerCase();
}

export function loadUserDictionary(): string[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const stored = window.localStorage.getItem(USER_DICTIONARY_KEY);
    if (!stored) {
      return [];
    }
    const parsed = JSON.parse(stored);
    if (Array.isArray(parsed)) {
      return parsed.filter((item) => typeof item === "string");
    }
    return [];
  } catch (error) {
    console.warn("Impossible de lire le dictionnaire utilisateur", error);
    return [];
  }
}

export function saveUserDictionary(words: string[]) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(USER_DICTIONARY_KEY, JSON.stringify(words));
  } catch (error) {
    console.warn("Impossible d'enregistrer le dictionnaire utilisateur", error);
  }
}

export function addToUserDictionary(word: string) {
  const normalized = normalizeWord(word);
  if (!normalized) {
    return;
  }

  const current = loadUserDictionary();
  if (current.some((entry) => normalizeWord(entry) === normalized)) {
    return;
  }

  saveUserDictionary([...current, word]);
}

export async function spellcheckText(
  text: string,
  language: SpellcheckLanguage,
  userDictionary: string[]
): Promise<SpellcheckError[]> {
  if (!text) {
    return [];
  }

  const spellchecker = await getSpellchecker(language);
  const userWords = new Set(userDictionary.map(normalizeWord));
  const errors: SpellcheckError[] = [];

  for (const match of text.matchAll(WORD_REGEX)) {
    const word = match[0];
    const start = match.index ?? 0;
    const end = start + word.length;
    const normalized = normalizeWord(word);

    if (!normalized || userWords.has(normalized)) {
      continue;
    }

    if (!spellchecker.correct(word)) {
      const suggestions = spellchecker.suggest(word).slice(0, 6);
      errors.push({ start, end, word, suggestions });
    }
  }

  return errors;
}

export function replaceWordOnce(text: string, error: SpellcheckError, replacement: string) {
  return text.slice(0, error.start) + replacement + text.slice(error.end);
}

export function replaceWordEverywhere(text: string, word: string, replacement: string) {
  if (!word) {
    return text;
  }
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`\\b${escaped}\\b`, "g");
  return text.replace(regex, replacement);
}

export function computeReplaceAllDelta(
  text: string,
  word: string,
  replacement: string,
  cursor: number
) {
  if (!word) {
    return 0;
  }

  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`\\b${escaped}\\b`, "g");
  let delta = 0;
  for (const match of text.matchAll(regex)) {
    const index = match.index ?? 0;
    if (index >= cursor) {
      break;
    }
    delta += replacement.length - word.length;
  }
  return delta;
}

export function escapeHtml(text: string) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
