import { useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import { useTranslation } from "react-i18next";
import type { JobName, RunCounts } from "#/client/types.gen.ts";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { runSummaryOptions } from "./run-summary.ts";

// One window's counts, grouped under its label (a fieldset groups any content, not only form
// controls): each count above what it counts. Failures are red only while there are any, so a
// healthy job reads calm. The legend floats, so it sits inside the tile like any first line.
function CountsTile({ label, counts }: { label: string; counts: RunCounts }) {
  const { t } = useTranslation();
  return (
    <fieldset className="grid gap-1 rounded-lg p-3 ring-1 ring-foreground/10">
      <legend className="float-left text-muted-foreground text-xs">{label}</legend>
      <dl className="flex gap-6">
        <div className="flex flex-col-reverse">
          <dt className="text-muted-foreground text-xs">{t("health.succeeded")}</dt>
          <dd className="font-medium text-xl tabular-nums">{counts.succeeded}</dd>
        </div>
        <div className="flex flex-col-reverse">
          <dt className="text-muted-foreground text-xs">{t("health.failed")}</dt>
          <dd
            className={cn(
              "font-medium text-xl tabular-nums",
              counts.failed > 0 && "text-destructive",
            )}
          >
            {counts.failed}
          </dd>
        </div>
      </dl>
    </fieldset>
  );
}

// A job's health at a glance (admins), above its run history: how many runs succeeded and
// failed in the last 24 hours and the last 7 days.
export function RunHealth({ job }: { job: JobName }) {
  const { t } = useTranslation();
  const summary = useQuery(runSummaryOptions(job));

  if (summary.isSuccess) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <CountsTile label={t("health.last24h")} counts={summary.data.last_24h} />
        <CountsTile label={t("health.last7d")} counts={summary.data.last_7d} />
      </div>
    );
  }
  if (summary.isError) {
    return <Unavailable onRetry={() => summary.refetch()} />;
  }
  return (
    <div role="status" className="grid gap-3 sm:grid-cols-2">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
  );
}
