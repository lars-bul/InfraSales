import { readRunSummaryOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { JobName } from "#/client/types.gen.ts";

/** The browser's time zone (an IANA name): the API counts in the person's hours and days. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

// How a job's runs went lately: its page's tiles.
export function runSummaryOptions(job: JobName) {
  return readRunSummaryOptions({ path: { job }, query: { timezone: browserTimeZone() } });
}
