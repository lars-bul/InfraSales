import { Link } from "@tanstack/react-router";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";
import { JOBS } from "./job-names.ts";
import { NextRun } from "./next-run.tsx";
import { scheduleSentence } from "./schedule-sentence.ts";

interface Props {
  entry: ConfigEntryRead;
  name: string; // the job's display name
  canEdit: boolean;
}

// On or Paused, as a badge.
export function JobState({ entry }: { entry: ConfigEntryRead }) {
  const { t } = useTranslation();
  const on = entry.value.enabled ?? true;
  return <Badge variant={on ? "success" : "outline"}>{t(on ? "jobs.on" : "jobs.paused")}</Badge>;
}

// When the job runs next: a countdown, or that it is not scheduled while paused.
export function NextRunOf({ entry }: { entry: ConfigEntryRead }) {
  const { t } = useTranslation();
  return (entry.value.enabled ?? true) && entry.next_run_at ? (
    <NextRun at={entry.next_run_at} />
  ) : (
    <span className="text-muted-foreground">{t("jobs.notScheduled")}</span>
  );
}

// What the job is and does, when it runs and next, and whether it is on: the terms of its
// details, on its page and in its sheet on the Jobs page. The sheet says what it does above them.
export function JobFacts({
  entry,
  described = true,
}: {
  entry: ConfigEntryRead;
  described?: boolean;
}) {
  const { t, i18n } = useTranslation();
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 text-sm">
      <dt className="text-muted-foreground">{t("jobs.details.id")}</dt>
      <dd>
        <code className="rounded bg-muted px-1 py-0.5 text-xs">{JOBS[entry.key]}</code>
      </dd>
      {described ? (
        <>
          <dt className="text-muted-foreground">{t("jobs.details.description")}</dt>
          <dd>{t(`jobs.descriptions.${entry.key}`)}</dd>
        </>
      ) : null}
      <dt className="text-muted-foreground">{t("jobs.details.schedule")}</dt>
      <dd>{scheduleSentence(entry.value, i18n)}</dd>
      <dt className="text-muted-foreground">{t("jobs.details.next")}</dt>
      <dd>
        <NextRunOf entry={entry} />
      </dd>
      <dt className="text-muted-foreground">{t("jobs.details.status")}</dt>
      <dd>
        <JobState entry={entry} />
      </dd>
    </dl>
  );
}

// The side panel of a job's page, as Databricks' "Job details": its facts. Admins get a link to
// its runs in the Job runs list.
export function JobDetails({ entry, name, canEdit }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const job = JOBS[entry.key];
  return (
    <aside aria-labelledby={id} className="grid content-start gap-4 rounded-lg border bg-card p-4">
      <h2 id={id} className="font-heading font-medium">
        {t("jobs.details.title")}
      </h2>
      <JobFacts entry={entry} />
      {canEdit ? (
        <Link
          to="/runs"
          search={{ job }}
          className="justify-self-start text-primary text-sm underline-offset-4 hover:underline"
        >
          {t("jobs.details.allRuns", { name })}
        </Link>
      ) : null}
    </aside>
  );
}
