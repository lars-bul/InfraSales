import type { TFunction } from "i18next";
import type { AuditEventRead, ConfigKey, JobName } from "#/client/types.gen.ts";
import type { en } from "#/i18n/locales/en.ts";
import { personOf } from "#/lib/person.ts";

type Table = keyof typeof en.audit.tables;

const SCHEDULES: readonly ConfigKey[] = ["scrape_schedule", "forecast_schedule"];
const JOBS: readonly JobName[] = ["scrape", "forecast"];
const TABLES: readonly Table[] = [
  "audit_event",
  "job_run",
  "auth_session",
  "source_version",
  "source",
];

function isOneOf<T extends string>(known: readonly T[], value: string | null): value is T {
  return known.some((item) => item === value);
}

// What an event acted on, named for a reader: a job, a schedule, a table, a person, or its code.
function targetOf(t: TFunction, event: AuditEventRead, reader: string): string {
  const { action, target } = event;
  if (action === "auth.revoked") {
    return person(t, target, reader);
  }
  if (action === "job.triggered" && isOneOf(JOBS, target)) {
    return t(`audit.jobs.${target}`);
  }
  if (action === "config.updated" && isOneOf(SCHEDULES, target)) {
    return t(`schedules.${target}`);
  }
  if (action === "retention.deleted" && isOneOf(TABLES, target)) {
    return t(`audit.tables.${target}`);
  }
  return target ?? "";
}

// The sentence's key: the action's own, or a variant for a failed sign-in or another setting.
function keyOf(event: AuditEventRead & { action: Action }) {
  if (event.action === "auth.login" && event.outcome === "failure") {
    return "audit.sentences.auth.loginFailed" as const;
  }
  if (event.action === "config.updated" && !isOneOf(SCHEDULES, event.target)) {
    return "audit.sentences.config.updatedSetting" as const;
  }
  return `audit.sentences.${event.action}` as const;
}

/** The actions the backend records, as the event-type filter offers them. */
export const ACTIONS = [
  "auth.login",
  "auth.logout",
  "auth.revoked",
  "config.updated",
  "job.triggered",
  "forecast.model_activated",
  "feed.created",
  "feed.deleted",
  "retention.pruned",
  "retention.deleted",
  "audit.read",
] as const;

export type Action = (typeof ACTIONS)[number];

/** Whether the interface knows `action`: has a sentence and an event type for it. */
export function isAction(action: string): action is Action {
  return isOneOf(ACTIONS, action);
}

/**
 * A person as the log shows them: their ID without the provider ("basic:alice" is "alice"),
 * "(you)" when it is the reader, and "system" for what nobody did.
 */
export function person(t: TFunction, subject: string | null, reader: string): string {
  if (subject === null) {
    return t("audit.system");
  }
  const name = personOf(subject);
  return subject === reader ? t("audit.you", { name }) : name;
}

/**
 * One event as a sentence: "alice changed the Source Collection schedule". An action the interface does
 * not know yet reads "alice: some.action"; a failure says so.
 */
export function sentence(t: TFunction, event: AuditEventRead, reader: string): string {
  const { action } = event;
  const failedSignIn = action === "auth.login" && event.outcome === "failure";
  const actor =
    failedSignIn && event.actor === null ? t("audit.unknownUser") : person(t, event.actor, reader);
  if (!isAction(action)) {
    return t("audit.unknown", { actor, action });
  }
  const text = t(keyOf({ ...event, action }), { actor, target: targetOf(t, event, reader) });
  return event.outcome === "failure" && !failedSignIn
    ? t("audit.failed", { sentence: text })
    : text;
}
