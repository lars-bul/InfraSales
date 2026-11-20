import { Link } from "@tanstack/react-router";
import { cn } from "cn";
import {
  ChevronRight,
  CircleCheck,
  CircleX,
  Clock,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { JobStatus, RunHistoryEntry, SourceCollectionResult } from "#/client/types.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";
import { Button } from "#/components/ui/button.tsx";
import { TableCell, TableRow } from "#/components/ui/table.tsx";
import { isJob, jobNameKey } from "#/features/jobs/job-names.ts";
import type { Translate } from "#/i18n/i18n.ts";
import { personOf } from "#/lib/person.ts";
import { FeedOutcomes } from "./feed-outcomes.tsx";

// Each status as an icon and a word in its colour, so it never rests on colour alone.
const STATUSES = {
  succeeded: { icon: CircleCheck, colour: "text-success", spin: false },
  failed: { icon: CircleX, colour: "text-destructive", spin: false },
  running: { icon: LoaderCircle, colour: "text-primary", spin: true },
  pending: { icon: Clock, colour: "text-muted-foreground", spin: false },
} as const satisfies Record<JobStatus, { icon: LucideIcon; colour: string; spin: boolean }>;

// Failed runs stand out while scanning the table, their details too.
const FAILED_TINT = "bg-destructive/10 dark:bg-destructive/20";

// The table's columns: Scheduled for, Started by, Status and Attempts, and Job and Result where
// shown.
const COLUMNS = 4;

// "the schedule", or "Run now · alice": the admin's ID without the sign-in provider.
function startedBy(run: RunHistoryEntry, t: Translate) {
  if (run.trigger === "schedule") {
    return t("history.triggers.schedule");
  }
  if (run.trigger === "follow_up") {
    return t("history.triggers.follow_up");
  }
  return run.triggered_by
    ? t("history.triggers.manualBy", { person: personOf(run.triggered_by) })
    : t("history.triggers.manual");
}

// "42 new Source Versions · 3 Feeds failed"; the Feeds only when some failed.
function summary(result: SourceCollectionResult, t: Translate) {
  const failed = result.failed_feeds.length;
  return [
    t("history.summary.versions", { count: result.versions_new }),
    ...(failed > 0 ? [t("history.summary.feeds", { count: failed })] : []),
  ].join(t("history.summary.separator"));
}

interface DetailsProps {
  run: RunHistoryEntry;
  scheduled: string; // when it was due, formatted
  time: Intl.DateTimeFormat;
}

// Why a run went as it did: its error, its times, what each Feed did (a result stored before
// that was kept: the Feeds that failed), the Sources it collected (on their page) and its trace.
function RunDetails({ run, scheduled, time }: DetailsProps) {
  const { t } = useTranslation();
  const feeds = run.result?.feeds ?? [];
  const failedFeeds = feeds.length > 0 ? [] : (run.result?.failed_feeds ?? []);
  const failedFeedsId = useId();
  return (
    <div className="grid gap-3 py-1">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted-foreground">{t("history.scheduled")}</dt>
        <dd>
          <time dateTime={run.scheduled_for}>{scheduled}</time>
        </dd>
        <dt className="text-muted-foreground">{t("history.details.finished")}</dt>
        <dd>
          {run.finished_at ? (
            <time dateTime={run.finished_at}>{time.format(new Date(run.finished_at))}</time>
          ) : (
            t("history.details.notFinished")
          )}
        </dd>
        {run.error ? (
          <>
            <dt className="text-muted-foreground">{t("history.details.error")}</dt>
            <dd>
              <code>{run.error}</code>
            </dd>
          </>
        ) : null}
      </dl>
      {feeds.length > 0 ? <FeedOutcomes feeds={feeds} /> : null}
      {failedFeeds.length > 0 ? (
        <div className="grid gap-1">
          <p id={failedFeedsId} className="text-muted-foreground">
            {t("history.details.failedFeeds")}
          </p>
          <ul aria-labelledby={failedFeedsId} className="grid gap-0.5">
            {failedFeeds.map(({ feed, reason }) => (
              <li key={feed}>{t("history.details.failedFeed", { feed, reason })}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {(run.result?.versions_new ?? 0) > 0 ? (
        <Link
          to="/sources"
          search={{ run: run.id }}
          className="justify-self-start text-primary underline underline-offset-4"
        >
          {t("sources.fromRun")}
        </Link>
      ) : null}
      {run.langfuse_url ? (
        <a
          href={run.langfuse_url}
          target="_blank"
          rel="noreferrer"
          className="justify-self-start text-primary underline underline-offset-4"
          aria-label={t("history.details.langfuseRun", { time: scheduled })}
        >
          {t("history.details.langfuse")}
        </a>
      ) : null}
    </div>
  );
}

// The run's job, linked to its page; a job the app no longer knows by its code.
function JobCell({ job }: { job: string }) {
  const { t } = useTranslation();
  if (!isJob(job)) {
    return <TableCell>{job}</TableCell>;
  }
  return (
    <TableCell>
      <Link
        to="/jobs/$job"
        params={{ job }}
        className="font-medium text-primary underline-offset-4 hover:underline"
      >
        {t(jobNameKey(job))}
      </Link>
    </TableCell>
  );
}

interface Props {
  run: RunHistoryEntry;
  withJob: boolean; // every job's runs: each names its job
  withResult: boolean; // Source Collection: its runs' results are summarised
  time: Intl.DateTimeFormat;
}

// The status; a success with Feeds that failed says so in amber beside it.
export function RunStatus({ status, feedsFailed }: { status: JobStatus; feedsFailed: boolean }) {
  const { t } = useTranslation();
  const { icon: Icon, colour, spin } = STATUSES[status];
  return (
    <span className="flex items-center gap-2">
      <span className={cn("inline-flex items-center gap-1.5 font-medium", colour)}>
        <Icon aria-hidden="true" className={cn("size-4", spin && "animate-spin")} />
        {t(`history.statuses.${status}`)}
      </span>
      {status === "succeeded" && feedsFailed ? (
        <Badge variant="warning">{t("history.feedsFailed")}</Badge>
      ) : null}
    </span>
  );
}

// Who started the run, as a sentence's end: "the schedule", or "Run now · alice".
export function StartedBy({ run }: { run: RunHistoryEntry }) {
  const { t } = useTranslation();
  return startedBy(run, t);
}

// The status as its icon alone, named for screen readers (and on hover) by `label`.
export function StatusIcon({ status, label }: { status: JobStatus; label: string }) {
  const { icon: Icon, colour, spin } = STATUSES[status];
  return (
    <Icon role="img" aria-label={label} className={cn("size-4", colour, spin && "animate-spin")}>
      <title>{label}</title>
    </Icon>
  );
}

// A run: when it was due, which job, who started it, how it went and what it did. Its toggle
// shows the details in a row below it.
export function RunRow({ run, withJob, withResult, time }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const details = useId();
  const tint = run.status === "failed" ? FAILED_TINT : undefined;
  const scheduled = time.format(new Date(run.scheduled_for));

  return (
    <>
      <TableRow className={tint}>
        <TableCell>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            aria-controls={expanded ? details : undefined}
            onClick={() => setExpanded(!expanded)}
          >
            <ChevronRight
              aria-hidden="true"
              className={cn("transition-transform", expanded && "rotate-90")}
            />
            <time dateTime={run.scheduled_for}>{scheduled}</time>
          </Button>
        </TableCell>
        {withJob ? <JobCell job={run.job} /> : null}
        <TableCell>{startedBy(run, t)}</TableCell>
        <TableCell>
          <RunStatus status={run.status} feedsFailed={(run.result?.failed_feeds.length ?? 0) > 0} />
        </TableCell>
        {withResult ? <TableCell>{run.result ? summary(run.result, t) : null}</TableCell> : null}
        <TableCell>{run.attempts}</TableCell>
      </TableRow>
      {expanded ? (
        <TableRow id={details} className={tint}>
          <TableCell
            colSpan={COLUMNS + Number(withJob) + Number(withResult)}
            className="whitespace-normal"
          >
            <RunDetails run={run} scheduled={scheduled} time={time} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}
