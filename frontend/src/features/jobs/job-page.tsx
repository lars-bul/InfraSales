import { Link } from "@tanstack/react-router";
import { cn } from "cn";
import { ChevronRightIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ConfigEntryRead, JobName } from "#/client/types.gen.ts";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs.tsx";
import { RunHealth } from "#/features/runs/run-health.tsx";
import { RunHistory } from "#/features/runs/run-history.tsx";
import { RunNowButton } from "#/features/runs/run-now.tsx";
import { RunSteps } from "#/features/runs/run-steps.tsx";
import { useRunNow } from "#/features/runs/use-run-now.ts";
import { ScheduleForm } from "#/features/schedules/schedule-form.tsx";
import { useScheduleSwitch } from "#/features/schedules/schedule-switch.tsx";
import { JobDetails } from "./job-details.tsx";
import { useJobEntries } from "./job-entries.ts";
import { JOBS } from "./job-names.ts";

interface ViewProps {
  entry: ConfigEntryRead;
  canEdit: boolean;
}

// A job's own page, laid out as Databricks' job page: a breadcrumb back to the jobs over its
// name, with Run now and the On/Off switch beside it (admins); its runs and its settings as tabs
// (admins, runs first); and its details in a panel at the side, for everyone.
function JobView({ entry, canEdit }: ViewProps) {
  const { t } = useTranslation();
  const job = JOBS[entry.key];
  const name = t(`schedules.${entry.key}`);
  const runNow = useRunNow(job, canEdit);
  const onOff = useScheduleSwitch(entry, name);

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <nav aria-label={t("jobs.breadcrumb")}>
            <ol className="flex items-center gap-1 text-muted-foreground text-sm">
              <li>
                <Link to="/jobs" className="hover:text-foreground">
                  {t("jobs.title")}
                </Link>
              </li>
              <li aria-hidden={true}>
                <ChevronRightIcon className="size-3.5" />
              </li>
            </ol>
          </nav>
          <h1 className="font-heading font-semibold text-2xl tracking-tight">{name}</h1>
        </div>
        {canEdit ? (
          <div className="flex items-center gap-3">
            <RunNowButton job={job} name={name} runNow={runNow} />
            {onOff.control}
          </div>
        ) : null}
      </header>
      {canEdit ? <div className="text-sm empty:hidden">{onOff.messages}</div> : null}
      <div
        className={cn("grid items-start gap-6", canEdit && "lg:grid-cols-[minmax(0,1fr)_20rem]")}
      >
        {canEdit ? (
          <div className="min-w-0">
            <RunSteps name={name} runNow={runNow} />
            <Tabs defaultValue="history">
              <TabsList variant="line" aria-label={t("jobs.tabs.label", { name })}>
                <TabsTrigger value="history">{t("jobs.tabs.history")}</TabsTrigger>
                <TabsTrigger value="settings">{t("jobs.tabs.settings")}</TabsTrigger>
              </TabsList>
              <TabsContent value="history" className="grid gap-4 pt-2">
                <RunHealth job={job} />
                <RunHistory filters={{ job }} name={name} />
              </TabsContent>
              <TabsContent value="settings" className="pt-2">
                <ScheduleForm entry={entry} />
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
        <JobDetails entry={entry} name={name} canEdit={canEdit} />
      </div>
    </div>
  );
}

// The page of `job`: its schedule as the route's loader read it (the loader made sure the job
// has one).
export function JobPage({ job, canEdit }: { job: JobName; canEdit: boolean }) {
  const entry = useJobEntries().find((candidate) => JOBS[candidate.key] === job);
  return entry ? <JobView entry={entry} canEdit={canEdit} /> : null;
}
