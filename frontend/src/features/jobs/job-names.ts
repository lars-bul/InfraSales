import type { ConfigKey, JobName } from "#/client/types.gen.ts";

// Which job each schedule starts; the compiler checks it covers every key.
export const JOBS = {
  scrape_schedule: "scrape",
  forecast_schedule: "forecast",
} as const satisfies Record<ConfigKey, JobName>;

// Which schedule starts each job, whose key names it in the locale ("schedules.scrape_schedule").
// The jobs that read what Source Collection stores (ADR 06 §5) will run after it, without a
// schedule of their own: they bring their own names and page back then.
export const SCHEDULES = {
  scrape: "scrape_schedule",
  forecast: "forecast_schedule",
} as const satisfies Record<JobName, ConfigKey>;

export const JOB_NAMES = Object.keys(SCHEDULES) as JobName[];

// A job the app knows, e.g. from an address or a run of a job removed since.
export function isJob(value: unknown): value is JobName {
  return typeof value === "string" && Object.hasOwn(SCHEDULES, value);
}

// The locale key of a job's name: its schedule's.
export function jobNameKey(job: JobName): `schedules.${ConfigKey}` {
  return `schedules.${SCHEDULES[job]}`;
}
