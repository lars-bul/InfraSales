import type { i18n as I18n } from "i18next";
import type { Schedule, Weekday } from "#/client/types.gen.ts";

const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const MONDAY = Date.parse("2024-01-01T00:00:00Z"); // weekday names come from Intl, per language
const DAY_MS = 86_400_000;
const MIN_RANGE = 3; // three days in a row or more read as a range: "Mon–Wed", but "Sat and Sun"
const MIDNIGHT = "00:00";

type Translator = Pick<I18n, "t" | "language">;

// The chosen days in week order, as runs of consecutive days: Mon, Tue, Wed, Fri → [[0, 2], [4, 4]].
function runsOf(days: readonly Weekday[]): [number, number][] {
  const runs: [number, number][] = [];
  for (const index of WEEKDAYS.flatMap((day, at) => (days.includes(day) ? [at] : []))) {
    const last = runs.at(-1);
    if (last && last[1] === index - 1) {
      last[1] = index;
    } else {
      runs.push([index, index]);
    }
  }
  return runs;
}

// "Every day", or the days as short names, ranges where three or more follow each other:
// "Mon–Fri", "Mon, Wed and Fri", "Mon–Wed, Fri and Sun".
function daysPhrase(days: readonly Weekday[], { t, language }: Translator): string {
  if (WEEKDAYS.every((day) => days.includes(day))) {
    return t("jobs.sentence.everyDay");
  }
  const short = new Intl.DateTimeFormat(language, { weekday: "short", timeZone: "UTC" });
  const name = (index: number) => short.format(MONDAY + index * DAY_MS);
  const parts = runsOf(days).flatMap(([first, last]) => {
    if (last - first + 1 >= MIN_RANGE) {
      return [t("jobs.sentence.range", { first: name(first), last: name(last) })];
    }
    return Array.from({ length: last - first + 1 }, (_, offset) => name(first + offset));
  });
  const final = parts.pop() ?? "";
  return parts.length === 0
    ? final
    : t("jobs.sentence.list", { list: parts.join(t("jobs.sentence.separator")), last: final });
}

/**
 * A schedule as one plain sentence: "Mon–Fri at 08:00 (Europe/Berlin)", "Every day, every 3 hours
 * (Europe/Berlin)". A repetition starting at another time than midnight says from when.
 */
export function scheduleSentence(schedule: Schedule, translator: Translator): string {
  const { t } = translator;
  const values = {
    days: daysPhrase(schedule.days, translator),
    time: schedule.time,
    timezone: schedule.timezone,
  };
  if (!schedule.every_hours) {
    return t("jobs.sentence.daily", values);
  }
  const every = t("jobs.sentence.every", { count: schedule.every_hours });
  return schedule.time === MIDNIGHT
    ? t("jobs.sentence.repeating", { ...values, every })
    : t("jobs.sentence.repeatingFrom", { ...values, every });
}
