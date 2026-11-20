import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { JOBS } from "./job-names.ts";

export type JobState = "all" | "on" | "paused";

/** Which jobs to list: those whose name or ID holds `text`, on or paused or both. */
export interface JobFilter {
  text: string;
  state: JobState;
}

export const EVERY_JOB: JobFilter = { text: "", state: "all" };

/** The states the filter offers, in its order. */
export const JOB_STATES = ["all", "on", "paused"] as const satisfies JobState[];

/** Whether the job matches: its name (as shown) or its ID, and its state. */
export function matches(entry: ConfigEntryRead, name: string, filter: JobFilter): boolean {
  const text = filter.text.trim().toLocaleLowerCase();
  const on = entry.value.enabled ?? true;
  return (
    (text === "" || name.toLocaleLowerCase().includes(text) || JOBS[entry.key].includes(text)) &&
    (filter.state === "all" || (filter.state === "on") === on)
  );
}
