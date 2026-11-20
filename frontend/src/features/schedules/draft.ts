import type { EveryHours, Schedule, Weekday } from "#/client/types.gen.ts";

const MIDNIGHT = "00:00"; // where a repeat starts unless told otherwise
const MONDAY: Weekday = "mon"; // the day once a week falls on unless one was chosen

// The repeats the API accepts, in order; the compiler checks the list is complete.
const REPEATS = { 1: null, 2: null, 3: null, 4: null, 6: null, 8: null, 12: null } satisfies Record<
  EveryHours,
  null
>;

const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/**
 * How often the job runs, as Okta's flow schedule offers it: every few hours, once a day, or
 * once a week (once a day on a single day). The API knows days, a time and a repeat only.
 */
type Frequency = "hour" | "day" | "week";

/**
 * The schedule being edited, and what the other frequencies would bring back: the time a daily or
 * weekly run is at, the hour a repeat starts from, how often it repeats. `onDays` is "only on"
 * ticked: the job runs on the days chosen, else every day.
 */
interface Draft {
  schedule: Schedule;
  frequency: Frequency;
  dailyTime: string;
  repeatFrom: string;
  hours: EveryHours;
  onDays: boolean;
}

function frequencyOf(schedule: Schedule): Frequency {
  if (schedule.every_hours) {
    return "hour";
  }
  return schedule.days.length === 1 ? "week" : "day";
}

function draftOf(schedule: Schedule): Draft {
  return {
    schedule,
    frequency: frequencyOf(schedule),
    dailyTime: schedule.time,
    repeatFrom: schedule.every_hours ? schedule.time : MIDNIGHT,
    hours: schedule.every_hours ?? 1,
    onDays: schedule.days.length < WEEKDAYS.length,
  };
}

// Every few hours from the hour it starts at, once a day at the daily time, both on the days it
// had (every day, coming from once a week); once a week on the first day it had.
function withFrequency(draft: Draft, frequency: Frequency): Draft {
  const { schedule } = draft;
  if (frequency === "week") {
    const day = WEEKDAYS.find((each) => schedule.days.includes(each)) ?? MONDAY;
    const weekly = { ...schedule, days: [day], every_hours: null, time: draft.dailyTime };
    return { ...draft, frequency, onDays: true, schedule: weekly };
  }
  const repeat =
    frequency === "hour"
      ? { every_hours: draft.hours, time: draft.repeatFrom }
      : { every_hours: null, time: draft.dailyTime };
  const fromWeek = draft.frequency === "week";
  return {
    ...draft,
    frequency,
    onDays: fromWeek ? false : draft.onDays,
    schedule: { ...schedule, ...repeat, days: fromWeek ? [...WEEKDAYS] : schedule.days },
  };
}

function withHours(draft: Draft, hours: EveryHours): Draft {
  return { ...draft, hours, schedule: { ...draft.schedule, every_hours: hours } };
}

// The time of a daily or weekly run, or the hour a repeat starts from.
function withTime(draft: Draft, time: string): Draft {
  const kept = draft.frequency === "hour" ? { repeatFrom: time } : { dailyTime: time };
  return { ...draft, ...kept, schedule: { ...draft.schedule, time } };
}

// "Only on" ticked keeps the days chosen; unticked, the job runs every day.
function withOnDays(draft: Draft, onDays: boolean): Draft {
  return onDays
    ? { ...draft, onDays }
    : { ...draft, onDays, schedule: { ...draft.schedule, days: [...WEEKDAYS] } };
}

function withDays(draft: Draft, days: Weekday[]): Draft {
  return { ...draft, schedule: { ...draft.schedule, days } };
}

const everyHours: readonly EveryHours[] = Object.keys(REPEATS).map(Number) as EveryHours[];

export {
  type Draft,
  draftOf,
  everyHours,
  type Frequency,
  WEEKDAYS,
  withDays,
  withFrequency,
  withHours,
  withOnDays,
  withTime,
};
