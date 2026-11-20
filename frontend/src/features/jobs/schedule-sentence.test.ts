import { expect, test } from "vitest";
import type { Schedule, Weekday } from "#/client/types.gen.ts";
import { i18n } from "#/i18n/i18n.ts";
import { scheduleSentence } from "./schedule-sentence.ts";

const WORKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri"];
const EVERY_DAY: Weekday[] = [...WORKDAYS, "sat", "sun"];

function schedule(days: Weekday[], time: string, everyHours: Schedule["every_hours"] = null) {
  return { days, time, timezone: "Europe/Berlin", enabled: true, every_hours: everyHours };
}

test.each([
  [schedule(WORKDAYS, "08:00"), "Mon–Fri at 08:00 (Europe/Berlin)"],
  [schedule(EVERY_DAY, "06:30"), "Every day at 06:30 (Europe/Berlin)"],
  [schedule(["mon"], "08:00"), "Mon at 08:00 (Europe/Berlin)"],
  [schedule(["mon", "wed", "fri"], "07:00"), "Mon, Wed and Fri at 07:00 (Europe/Berlin)"],
  [schedule(["sat", "sun"], "10:00"), "Sat and Sun at 10:00 (Europe/Berlin)"],
  [
    schedule(["mon", "tue", "wed", "fri", "sun"], "09:00"),
    "Mon–Wed, Fri and Sun at 09:00 (Europe/Berlin)",
  ],
])("a schedule once a day reads as a sentence: %o", (value, sentence) => {
  expect(scheduleSentence(value, i18n)).toBe(sentence);
});

test.each([
  [schedule(EVERY_DAY, "00:00", 3), "Every day, every 3 hours (Europe/Berlin)"],
  [schedule(EVERY_DAY, "00:00", 1), "Every day, every hour (Europe/Berlin)"],
  [schedule(WORKDAYS, "06:00", 3), "Mon–Fri, every 3 hours from 06:00 (Europe/Berlin)"],
])("a repeating schedule reads as a sentence: %o", (value, sentence) => {
  expect(scheduleSentence(value, i18n)).toBe(sentence);
});
