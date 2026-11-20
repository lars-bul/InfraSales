import { expect, test } from "vitest";
import type { Schedule } from "#/client/types.gen.ts";
import {
  draftOf,
  WEEKDAYS,
  withDays,
  withFrequency,
  withHours,
  withOnDays,
  withTime,
} from "./draft.ts";

const weekly: Schedule = {
  days: ["mon"],
  time: "08:00",
  timezone: "Europe/Berlin",
  enabled: true,
  every_hours: null,
};
const workdays: Schedule = { ...weekly, days: ["mon", "tue", "wed", "thu", "fri"] };
const everyDay: Schedule = { ...weekly, days: [...WEEKDAYS] };

test("a stored schedule opens on its frequency: a repeat, one day, or several", () => {
  expect(draftOf({ ...everyDay, every_hours: 3 }).frequency).toBe("hour");
  expect(draftOf(weekly).frequency).toBe("week");
  expect(draftOf(workdays).frequency).toBe("day");
  expect(draftOf(everyDay).frequency).toBe("day");
});

test("Only on is ticked when the days are not all of them", () => {
  expect(draftOf(workdays).onDays).toBe(true);
  expect(draftOf(everyDay).onDays).toBe(false);
});

test("every few hours starts from midnight, on the days it had", () => {
  const hourly = withHours(withFrequency(draftOf(workdays), "hour"), 6).schedule;

  expect(hourly).toEqual({ ...workdays, every_hours: 6, time: "00:00" });
});

test("a repeat's start and a daily run's time are kept apart", () => {
  const hourly = withTime(withFrequency(draftOf(workdays), "hour"), "06:00");

  expect(hourly.schedule.time).toBe("06:00");
  const daily = withFrequency(hourly, "day");
  expect(daily.schedule).toEqual(workdays); // back at 08:00, no repeat
  expect(withFrequency(daily, "hour").schedule.time).toBe("06:00");
});

test("once a week keeps the first day it had; once a day from it runs every day", () => {
  const week = withFrequency(draftOf(workdays), "week");
  expect(week.schedule.days).toEqual(["mon"]);

  const day = withFrequency(withDays(week, ["fri"]), "day");
  expect(day.schedule.days).toEqual([...WEEKDAYS]);
  expect(day.onDays).toBe(false);
});

test("every few hours from once a week runs every day", () => {
  const hourly = withFrequency(draftOf(weekly), "hour");

  expect(hourly.schedule.days).toEqual([...WEEKDAYS]);
  expect(hourly.onDays).toBe(false);
});

test("once a week from every day falls on Monday", () => {
  expect(withFrequency(draftOf({ ...everyDay, days: [] }), "week").schedule.days).toEqual(["mon"]);
});

test("unticking Only on runs every day; ticking it keeps the days until some are dropped", () => {
  const all = withOnDays(draftOf(workdays), false);
  expect(all.schedule.days).toEqual([...WEEKDAYS]);

  const ticked = withOnDays(all, true);
  expect(ticked.onDays).toBe(true);
  expect(ticked.schedule.days).toEqual([...WEEKDAYS]);
});

test("a stored repeat from another time keeps it", () => {
  const fromSix = { ...everyDay, time: "06:00", every_hours: 3 as const };

  expect(draftOf(fromSix).repeatFrom).toBe("06:00");
  expect(withFrequency(draftOf(fromSix), "hour").schedule).toEqual(fromSix);
});
