import * as React from "react";
import type { ChangeEvent, TextareaHTMLAttributes } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSpellcheckSettings } from "../app/spellcheckSettings";
import {
  addToUserDictionary,
  computeReplaceAllDelta,
  escapeHtml,
  loadUserDictionary,
  replaceWordEverywhere,
  replaceWordOnce,
  spellcheckText,
  type SpellcheckError
} from "../lib/spellcheck";

export interface AppTextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  noSpellcheck?: boolean;
}

function createChangeEvent(value: string) {
  return { target: { value } } as ChangeEvent<HTMLTextAreaElement>;
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

function buildHighlightHtml(text: string, errors: SpellcheckError[]) {
  if (!errors.length) {
    return escapeHtml(text);
  }

  const sorted = [...errors].sort((a, b) => a.start - b.start);
  let result = "";
  let cursor = 0;

  sorted.forEach((error) => {
    if (error.start < cursor) {
      return;
    }
    result += escapeHtml(text.slice(cursor, error.start));
    const word = escapeHtml(text.slice(error.start, error.end));
    result += `<mark class=\"rounded-sm bg-red-500/10 underline decoration-red-500 decoration-dotted\">${word}</mark>`;
    cursor = error.end;
  });

  result += escapeHtml(text.slice(cursor));
  return result;
}

const MIN_TEXTAREA_HEIGHT = 180;
const MAX_TEXTAREA_HEIGHT = 360;

export const AppTextArea = React.forwardRef<HTMLTextAreaElement, AppTextAreaProps>(
  ({ className, noSpellcheck, onChange, value, style, ...props }, ref) => {
    const { settings } = useSpellcheckSettings();
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);
    const mirrorRef = useRef<HTMLDivElement | null>(null);
    const [errors, setErrors] = useState<SpellcheckError[]>([]);
    const [isChecking, setIsChecking] = useState(false);
    const [activeError, setActiveError] = useState<SpellcheckError | null>(null);
    const [textareaHeight, setTextareaHeight] = useState<number | null>(null);
    const [isOverflowing, setIsOverflowing] = useState(false);

    const textValue = typeof value === "string" ? value : "";
    const placeholderText = props.placeholder ?? "";
    const hasPlaceholder = !textValue && Boolean(placeholderText);
    const displayText = hasPlaceholder ? placeholderText : textValue;

    const isSpellcheckable = settings.enabled && !noSpellcheck && typeof value === "string";

    const mergedRef = (node: HTMLTextAreaElement | null) => {
      textareaRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = node;
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

    const handleScroll = () => {
      if (mirrorRef.current && textareaRef.current) {
        mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
        mirrorRef.current.scrollLeft = textareaRef.current.scrollLeft;
      }
    };

    const handleClick = () => {
      if (!textareaRef.current) {
        return;
      }
      const cursor = textareaRef.current.selectionStart ?? 0;
      const hit = errors.find((error) => cursor >= error.start && cursor <= error.end);
      setActiveError(hit ?? null);
    };

    const handleReplace = (error: SpellcheckError, replacement: string, replaceAll = false) => {
      if (typeof value !== "string") {
        return;
      }

      const textarea = textareaRef.current;
      const selectionStart = textarea?.selectionStart ?? value.length;
      const selectionEnd = textarea?.selectionEnd ?? value.length;
      const scrollTop = textarea?.scrollTop ?? 0;

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
        if (textarea) {
          textarea.setSelectionRange(nextSelectionStart, nextSelectionEnd);
          textarea.scrollTop = scrollTop;
        }
      });
      runSpellcheck();
    };

    const handleAddToDictionary = (word: string) => {
      addToUserDictionary(word);
      runSpellcheck();
    };

    const highlightHtml = useMemo(() => {
      if (!isSpellcheckable || typeof value !== "string") {
        return escapeHtml(displayText);
      }
      if (hasPlaceholder) {
        return escapeHtml(displayText);
      }
      return buildHighlightHtml(textValue, errors);
    }, [displayText, errors, hasPlaceholder, isSpellcheckable, textValue, value]);

    const syncMirrorHeight = React.useCallback((height: number) => {
      setTextareaHeight(height);
      if (mirrorRef.current) {
        mirrorRef.current.style.height = `${height}px`;
      }
    }, []);

    useEffect(() => {
      if (!textareaRef.current) {
        return;
      }

      const textarea = textareaRef.current;
      const currentHeight = textarea.getBoundingClientRect().height || MIN_TEXTAREA_HEIGHT;
      textarea.style.height = "auto";
      const rawHeight = textarea.scrollHeight;
      const desiredHeight = Math.min(
        Math.max(rawHeight, MIN_TEXTAREA_HEIGHT),
        MAX_TEXTAREA_HEIGHT
      );
      const nextHeight = Math.max(currentHeight, desiredHeight);

      textarea.style.height = `${nextHeight}px`;
      setIsOverflowing(rawHeight > MAX_TEXTAREA_HEIGHT);
      syncMirrorHeight(nextHeight);
    }, [syncMirrorHeight, textValue]);

    useEffect(() => {
      if (!textareaRef.current) {
        return;
      }
      const textarea = textareaRef.current;
      const observer = new ResizeObserver((entries) => {
        entries.forEach((entry) => {
          syncMirrorHeight(entry.contentRect.height);
        });
      });
      observer.observe(textarea);
      return () => observer.disconnect();
    }, [syncMirrorHeight]);

    const baseStyle: React.CSSProperties = {
      ...style,
      minHeight: MIN_TEXTAREA_HEIGHT,
      resize: "vertical"
    };

    if (!isSpellcheckable) {
      return (
        <textarea
          ref={mergedRef}
          value={value}
          onChange={onChange}
          className={className}
          style={{
            ...baseStyle,
            height: textareaHeight ? `${textareaHeight}px` : style?.height,
            overflowY: isOverflowing ? "auto" : "hidden"
          }}
          {...props}
        />
      );
    }

    const layoutClasses = extractLayoutClasses(className);

    return (
      <div className={["relative", layoutClasses].filter(Boolean).join(" ")}>
        <div
          ref={mirrorRef}
          aria-hidden
          className={[
            "absolute inset-0 overflow-hidden whitespace-pre-wrap break-words rounded-md border border-transparent px-3 py-2 text-sm text-slate-100",
            hasPlaceholder ? "text-slate-500" : null,
            className
          ]
            .filter(Boolean)
            .join(" ")}
          style={{
            minHeight: MIN_TEXTAREA_HEIGHT,
            height: textareaHeight ? `${textareaHeight}px` : undefined
          }}
          dangerouslySetInnerHTML={{ __html: highlightHtml || "" }}
        />
        <textarea
          ref={mergedRef}
          value={value}
          onChange={onChange}
          onScroll={handleScroll}
          onClick={handleClick}
          spellCheck={false}
          className={[
            "relative bg-transparent text-transparent caret-slate-100",
            "rounded-md border border-slate-800 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none",
            className
          ]
            .filter(Boolean)
            .join(" ")}
          style={{
            ...baseStyle,
            height: textareaHeight ? `${textareaHeight}px` : style?.height,
            overflowY: isOverflowing ? "auto" : "hidden",
            caretColor: "#f8fafc",
            backgroundColor: "transparent",
            color: "transparent"
          }}
          {...props}
        />
        <button
          type="button"
          onClick={runSpellcheck}
          className="absolute right-2 top-2 rounded-md border border-slate-700 px-2 py-1 text-[10px] font-semibold text-slate-200 hover:border-slate-500 hover:bg-slate-800"
          aria-label="Vérifier l'orthographe"
        >
          {isChecking ? "..." : "ABC✓"}
        </button>
        {activeError ? (
          <div className="absolute right-2 top-10 z-10 w-64 rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 shadow-lg">
            <p className="font-semibold text-red-300">{activeError.word}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {activeError.suggestions.length > 0 ? (
                activeError.suggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => handleReplace(activeError, suggestion)}
                    className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
                  >
                    Remplacer par “{suggestion}”
                  </button>
                ))
              ) : (
                <span className="text-[11px] text-slate-500">Aucune suggestion</span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() =>
                  handleReplace(activeError, activeError.suggestions[0] ?? activeError.word, true)
                }
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
              >
                Remplacer partout
              </button>
              <button
                type="button"
                onClick={() => setActiveError(null)}
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
              >
                Ignorer
              </button>
              <button
                type="button"
                onClick={() => handleAddToDictionary(activeError.word)}
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-500 hover:bg-slate-800"
              >
                Ajouter au dictionnaire
              </button>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
);

AppTextArea.displayName = "AppTextArea";
