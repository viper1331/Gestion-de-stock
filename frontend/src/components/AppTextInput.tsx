import type { ChangeEvent, InputHTMLAttributes } from "react";
import { forwardRef, useEffect, useMemo, useRef, useState } from "react";

import { useSpellcheckSettings } from "../app/spellcheckSettings";
import {
  addToUserDictionary,
  computeReplaceAllDelta,
  loadUserDictionary,
  replaceWordEverywhere,
  replaceWordOnce,
  spellcheckText,
  type SpellcheckError
} from "../lib/spellcheck";

export interface AppTextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  noSpellcheck?: boolean;
}

function isSpellcheckableType(type?: string) {
  if (!type) {
    return true;
  }
  return type === "text";
}

function createChangeEvent(value: string) {
  return { target: { value } } as ChangeEvent<HTMLInputElement>;
}

function extractLayoutClasses(className?: string) {
  if (!className) {
    return "";
  }
  return className
    .split(" ")
    .filter((token) =>
      [
        "w-",
        "h-",
        "flex-",
        "grow",
        "basis-",
        "min-w",
        "max-w",
        "min-h",
        "max-h"
      ].some((prefix) => token.startsWith(prefix))
    )
    .join(" ");
}

export const AppTextInput = forwardRef<HTMLInputElement, AppTextInputProps>(
  ({ className, noSpellcheck, type, onChange, value, ...props }, ref) => {
    const { settings } = useSpellcheckSettings();
    const localRef = useRef<HTMLInputElement>(null);
    const [errors, setErrors] = useState<SpellcheckError[]>([]);
    const [isChecking, setIsChecking] = useState(false);
    const [activeError, setActiveError] = useState<SpellcheckError | null>(null);

    const resolvedType = type ?? "text";
    const isSpellcheckable =
      settings.enabled && !noSpellcheck && isSpellcheckableType(resolvedType) && typeof value === "string";

    const mergedRef = (node: HTMLInputElement | null) => {
      localRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
    };

    const runSpellcheck = async () => {
      if (!isSpellcheckable || typeof value !== "string") {
        return;
      }
      setIsChecking(true);
      const result = await spellcheckText(value, settings.language, loadUserDictionary());
      setErrors(result);
      setActiveError(result[0] ?? null);
      setIsChecking(false);
    };

    useEffect(() => {
      if (!settings.live || !isSpellcheckable) {
        return;
      }

      const handle = window.setTimeout(() => {
        runSpellcheck();
      }, 700);

      return () => window.clearTimeout(handle);
    }, [settings.live, isSpellcheckable, value]);

    const handleReplace = (error: SpellcheckError, replacement: string, replaceAll = false) => {
      if (typeof value !== "string") {
        return;
      }
      const input = localRef.current;
      const selectionStart = input?.selectionStart ?? value.length;
      const selectionEnd = input?.selectionEnd ?? value.length;

      let nextValue = value;
      let nextSelectionStart = selectionStart;
      let nextSelectionEnd = selectionEnd;

      if (replaceAll) {
        nextValue = replaceWordEverywhere(value, error.word, replacement);
        const delta = computeReplaceAllDelta(value, error.word, replacement, selectionStart);
        nextSelectionStart = selectionStart + delta;
        nextSelectionEnd = selectionEnd + delta;
      } else {
        nextValue = replaceWordOnce(value, error, replacement);
        const delta = replacement.length - (error.end - error.start);
        if (selectionStart >= error.end) {
          nextSelectionStart = selectionStart + delta;
          nextSelectionEnd = selectionEnd + delta;
        } else if (selectionStart >= error.start) {
          nextSelectionStart = error.start + replacement.length;
          nextSelectionEnd = nextSelectionStart;
        }
      }

      onChange?.(createChangeEvent(nextValue));
      requestAnimationFrame(() => {
        if (input) {
          input.setSelectionRange(nextSelectionStart, nextSelectionEnd);
        }
      });
      runSpellcheck();
    };

    const handleIgnore = () => {
      setActiveError(null);
    };

    const handleAddToDictionary = (word: string) => {
      addToUserDictionary(word);
      runSpellcheck();
    };

    const suggestions = useMemo(() => activeError?.suggestions ?? [], [activeError]);

    if (!isSpellcheckable) {
      return (
        <input
          ref={mergedRef}
          type={resolvedType}
          value={value}
          onChange={onChange}
          className={className}
          {...props}
        />
      );
    }

    const layoutClasses = extractLayoutClasses(className);

    return (
      <div className={["relative", layoutClasses].filter(Boolean).join(" ")}>
        <input
          ref={mergedRef}
          type={resolvedType}
          value={value}
          onChange={onChange}
          spellCheck={false}
          className={["pr-12", className].filter(Boolean).join(" ")}
          {...props}
        />
        <button
          type="button"
          onClick={runSpellcheck}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md border border-slate-700 px-2 py-1 text-[10px] font-semibold text-slate-200 hover:border-slate-500 hover:bg-slate-800"
          aria-label="Vérifier l'orthographe"
        >
          {isChecking ? "..." : "ABC✓"}
        </button>
        {errors.length > 0 ? (
          <div className="mt-2 space-y-2 rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200">
            <p className="font-semibold text-slate-300">Mots suspects</p>
            {errors.map((error) => (
              <div key={`${error.start}-${error.word}`} className="space-y-1">
                <button
                  type="button"
                  onClick={() => setActiveError(error)}
                  className="text-left text-xs font-semibold text-red-300 hover:text-red-200"
                >
                  {error.word}
                </button>
                {activeError?.word === error.word ? (
                  <div className="flex flex-wrap gap-2">
                    {suggestions.length > 0 ? (
                      suggestions.map((suggestion) => (
                        <button
                          key={suggestion}
                          type="button"
                          onClick={() => handleReplace(error, suggestion)}
                          className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
                        >
                          Remplacer par “{suggestion}”
                        </button>
                      ))
                    ) : (
                      <span className="text-[11px] text-slate-500">Aucune suggestion</span>
                    )}
                    <button
                      type="button"
                      onClick={() => handleReplace(error, suggestions[0] ?? error.word, true)}
                      className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
                    >
                      Remplacer partout
                    </button>
                    <button
                      type="button"
                      onClick={handleIgnore}
                      className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
                    >
                      Ignorer
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAddToDictionary(error.word)}
                      className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
                    >
                      Ajouter au dictionnaire
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
);

AppTextInput.displayName = "AppTextInput";
