const SECOND_MS = 1000;
const DAYS_PER_MONTH = 30; // near enough for "2 months ago"
const MONTHS_PER_YEAR = 12;
// Each unit, and how many of it make the next: the largest that fits is shown ("3 hours ago",
// "yesterday", "2 months ago").
const UNITS = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", DAYS_PER_MONTH],
  ["month", MONTHS_PER_YEAR],
  ["year", Number.POSITIVE_INFINITY],
] as const;

// How long ago an instant was, in the language's words: "3 hours ago", "yesterday".
export function ago(at: string, language: string): string {
  const format = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
  let amount = (Date.parse(at) - Date.now()) / SECOND_MS;
  for (const [unit, size] of UNITS) {
    if (Math.abs(Math.round(amount)) < size) {
      return format.format(Math.round(amount), unit);
    }
    amount /= size;
  }
  return format.format(Math.round(amount), "year"); // not reached: years never run out
}
