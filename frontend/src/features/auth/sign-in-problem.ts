// Why the backend sent the browser back from signing in (`?signin=…`).
const PROBLEMS = ["failed", "denied", "unavailable"] as const;

export type Problem = (typeof PROBLEMS)[number];

/**
 * The known problem in a URL's search parameters; anything else is ignored. The key is always
 * there, so an unknown value never reaches the page (the router keeps unvalidated parameters).
 */
export function problemIn({ signin }: Record<string, unknown>): { signin?: Problem | undefined } {
  return { signin: PROBLEMS.find((known) => known === signin) };
}
