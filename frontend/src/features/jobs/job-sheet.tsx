import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { EllipsisIcon } from "lucide-react";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import { listJobRunsOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { ConfigEntryRead, JobName } from "#/client/types.gen.ts";
import { Button, buttonVariants } from "#/components/ui/button.tsx";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "#/components/ui/sheet.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { RunHealth } from "#/features/runs/run-health.tsx";
import { RunNowButton } from "#/features/runs/run-now.tsx";
import { RunStatus, StartedBy } from "#/features/runs/run-row.tsx";
import { RunSteps } from "#/features/runs/run-steps.tsx";
import { useRunNow } from "#/features/runs/use-run-now.ts";
import { useScheduleSwitch } from "#/features/schedules/schedule-switch.tsx";
import { JobFacts } from "./job-details.tsx";
import { JOBS } from "./job-names.ts";

const COUNT = 5; // as the row's recent runs, so both share one request

interface Props {
  entry: ConfigEntryRead;
  name: string; // the job's display name
  canEdit: boolean;
}

// A part of the sheet under its own heading.
function Part({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="grid gap-3">
      <h3 id={id} className="font-heading font-medium text-sm">
        {title}
      </h3>
      {children}
    </section>
  );
}

// The job's last runs, newest first: how each went, when it was due and who started it.
function LatestRuns({ job }: { job: JobName }) {
  const { t, i18n } = useTranslation();
  const latest = useQuery(listJobRunsOptions({ query: { job, limit: COUNT } }));

  if (latest.isError) {
    return <Unavailable onRetry={() => latest.refetch()} />;
  }
  if (!latest.isSuccess) {
    return (
      <div role="status" className="grid gap-2">
        <span className="sr-only">{t("app.loading")}</span>
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
      </div>
    );
  }
  if (latest.data.length === 0) {
    return <p className="text-muted-foreground">{t("history.empty.title")}</p>;
  }
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <ul className="divide-y rounded-lg border">
      {latest.data.slice(0, COUNT).map((run) => (
        <li key={run.id} className="grid gap-0.5 px-3 py-2">
          <RunStatus status={run.status} feedsFailed={(run.result?.failed_feeds.length ?? 0) > 0} />
          <span className="text-muted-foreground">
            <time dateTime={run.scheduled_for}>{time.format(new Date(run.scheduled_for))}</time>
            {t("history.summary.separator")}
            <StartedBy run={run} />
          </span>
        </li>
      ))}
    </ul>
  );
}

// What admins can do and see from the sheet, as on the job's page: Run now and the On/Off switch,
// the run's progress, how its runs went lately and its last runs.
function AdminParts({ entry, name }: Omit<Props, "canEdit">) {
  const { t } = useTranslation();
  const job = JOBS[entry.key];
  const runNow = useRunNow(job, true);
  const onOff = useScheduleSwitch(entry, name);
  return (
    <>
      <div className="grid gap-2">
        <div className="flex items-center gap-3">
          <RunNowButton job={job} name={name} runNow={runNow} />
          {onOff.control}
        </div>
        <div className="empty:hidden">{onOff.messages}</div>
        <RunSteps name={name} runNow={runNow} />
      </div>
      <Part title={t("jobs.sheet.health")}>
        <RunHealth job={job} />
      </Part>
      <Part title={t("jobs.sheet.latest")}>
        <LatestRuns job={job} />
      </Part>
    </>
  );
}

// The "…" at the end of a job's row: the job at a glance in a sheet from the right, without
// leaving the list, as Databricks' job list peeks into a job. Everyone sees its details; admins,
// as on its page, also Run now, the On/Off switch and its runs. Its page has the rest.
export function JobSheet({ entry, name, canEdit }: Props) {
  const { t } = useTranslation();
  const job = JOBS[entry.key];
  return (
    <Sheet>
      <SheetTrigger
        render={
          <Button variant="ghost" size="icon-sm" aria-label={t("jobs.sheet.open", { name })} />
        }
      >
        <EllipsisIcon aria-hidden={true} />
      </SheetTrigger>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:sm:max-w-md">
        <SheetHeader className="border-b pe-12">
          <SheetTitle>{name}</SheetTitle>
          {/* what it does, so its facts below leave it out */}
          <SheetDescription>{t(`jobs.descriptions.${entry.key}`)}</SheetDescription>
        </SheetHeader>
        <div className="grid content-start gap-6 p-4">
          {canEdit ? <AdminParts entry={entry} name={name} /> : null}
          <Part title={t("jobs.details.title")}>
            <JobFacts entry={entry} described={false} />
          </Part>
        </div>
        <SheetFooter className="flex-row flex-wrap border-t">
          <Link to="/jobs/$job" params={{ job }} className={buttonVariants()}>
            {t("jobs.sheet.page")}
          </Link>
          {canEdit ? (
            <Link to="/runs" search={{ job }} className={buttonVariants({ variant: "outline" })}>
              {t("jobs.details.allRuns", { name })}
            </Link>
          ) : null}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
