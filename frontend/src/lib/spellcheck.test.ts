import { describe, expect, it, beforeEach } from "vitest";

import {
  addToUserDictionary,
  computeReplaceAllDelta,
  loadUserDictionary,
  replaceWordEverywhere,
  replaceWordOnce,
  spellcheckText,
  type SpellcheckError
} from "./spellcheck";

describe("spellcheck helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("detects misspellings and provides suggestions", async () => {
    const errors = await spellcheckText("bonjourr", "fr", []);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]?.suggestions.length).toBeGreaterThan(0);
  });

  it("replaces one occurrence and keeps cursor delta", () => {
    const error: SpellcheckError = { start: 0, end: 5, word: "bonjr", suggestions: [] };
    expect(replaceWordOnce("bonjr test", error, "bonjour")).toBe("bonjour test");
    expect(computeReplaceAllDelta("bonjr test", "bonjr", "bonjour", 3)).toBe(2);
  });

  it("replaces all occurrences", () => {
    expect(replaceWordEverywhere("salut salut", "salut", "bonjour")).toBe("bonjour bonjour");
  });

  it("adds words to the user dictionary", () => {
    addToUserDictionary("GSP");
    expect(loadUserDictionary()).toContain("GSP");
  });
});
