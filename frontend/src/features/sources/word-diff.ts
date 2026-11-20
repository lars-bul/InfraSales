import { type Change, diffWords } from "diff";

const WHITESPACE = /\s+/;
const TOKEN = /\S+\s*/g;
const LEADING_SPACE = /^\s*/;

function words(text: string): number {
  return text.split(WHITESPACE).filter(Boolean).length;
}

function changeOf(part: Change): Stretch["change"] {
  if (part.added) {
    return "added";
  }
  return part.removed ? "removed" : "kept";
}

/** A stretch of the newer text: kept, added to the older one, or removed from it. */
export interface Stretch {
  text: string;
  change: "kept" | "added" | "removed";
}

export interface WordDiff {
  stretches: Stretch[];
  added: number; // words
  removed: number; // words
}

/**
 * What changed from `before` to `after`, word by word (jsdiff's `diffWords`): prose re-wraps, so
 * lines are no unit for an article. Whitespace alone is no change.
 */
export function wordDiff(before: string, after: string): WordDiff {
  const stretches = diffWords(before, after).map(
    (part): Stretch => ({ text: part.value, change: changeOf(part) }),
  );
  const count = (change: Stretch["change"]) =>
    stretches
      .filter((stretch) => stretch.change === change)
      .reduce((sum, stretch) => sum + words(stretch.text), 0);
  return { stretches, added: count("added"), removed: count("removed") };
}

/** Unchanged words left out between two changes: their count. */
export interface Skipped {
  change: "skipped";
  words: number;
}

/**
 * The changes with only `context` unchanged words around each, as GitHub folds unchanged
 * lines: long unchanged stretches between them become one `Skipped` each.
 */
export function aroundChanges(stretches: Stretch[], context = 25): (Stretch | Skipped)[] {
  const last = stretches.length - 1;
  return stretches.flatMap((stretch, index): (Stretch | Skipped)[] => {
    const tokens = stretch.text.match(TOKEN) ?? [];
    const head = index > 0 ? context : 0; // after a change
    const tail = index < last ? context : 0; // before a change
    if (stretch.change !== "kept" || tokens.length <= head + tail + context) {
      return [stretch];
    }
    const lead = stretch.text.match(LEADING_SPACE)?.[0] ?? "";
    const kept = (text: string): Stretch[] => (text ? [{ text, change: "kept" }] : []);
    return [
      ...kept(head ? lead + tokens.slice(0, head).join("") : ""),
      { change: "skipped", words: tokens.length - head - tail },
      ...kept(tokens.slice(tokens.length - tail).join("")),
    ];
  });
}
