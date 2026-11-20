import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import type { BucketCounts, RunCounts } from "#/client/types.gen.ts";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { activityQuery, type RunFilters } from "#/features/runs/run-query.ts";
import { RunsChart } from "./runs-chart.tsx";

const TILE = "grid content-start gap-1 rounded-lg bg-card p-3 ring-1 ring-foreground/10"; // as cards

// The buckets added up: the figures count what the chart shows.
function addUp(buckets: BucketCounts[]): RunCounts {
  return buckets.reduce(
    (total, bucket) => ({
      succeeded: total.succeeded + bucket.succeeded,
      failed: total.failed + bucket.failed,
    }),
    { succeeded: 0, failed: 0 },
  );
}

function Figure({
  label,
  value,
  share,
}: {
  label: string;
  value: number;
  share?: string | undefined;
}) {
  return (
    <div className={TILE}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium text-xl tabular-nums">
        {value}
        {share ? (
          <>
            {" "}
            <span className="font-normal text-muted-foreground text-xs">{share}</span>
          </>
        ) : null}
      </dd>
    </div>
  );
}

interface Props {
  filters: RunFilters;
  name?: string | undefined; // the one job's display name, when the filters pick one out
}

// Above the Job runs: the runs the filters list at a glance, over the time they pick (the last
// 7 days unless a start or end is set): how many ended and how, with a chart per hour or day.
export function RunOverview({ filters, name }: Props) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const activity = useQuery(activityQuery(filters));
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent" });
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });

  const { start, end } = filters;
  let when: string = t("health.overview.week");
  if (start && end) {
    when = time.formatRange(new Date(start), new Date(end));
  } else if (start) {
    when = t("health.overview.since", { start: time.format(new Date(start)) });
  } else if (end) {
    when = t("health.overview.until", { end: time.format(new Date(end)) });
  }

  let content: ReactNode;
  if (activity.isSuccess) {
    const { buckets, unit } = activity.data;
    const total = addUp(buckets);
    const runs = total.succeeded + total.failed;
    const share = (count: number) => (runs > 0 ? percent.format(count / runs) : undefined);
    content = (
      <div className="grid gap-3 sm:grid-cols-4">
        <dl className="grid grid-cols-3 content-start gap-3 sm:grid-cols-1">
          <Figure label={t("health.overview.runs")} value={runs} />
          <Figure
            label={t("health.succeeded")}
            value={total.succeeded}
            share={share(total.succeeded)}
          />
          <Figure label={t("health.failed")} value={total.failed} share={share(total.failed)} />
        </dl>
        <div className={`${TILE} sm:col-span-3`}>
          <p aria-hidden="true" className="text-muted-foreground text-xs">
            {t(unit === "hour" ? "health.overview.perHour" : "health.overview.perDay")}
          </p>
          <RunsChart buckets={buckets} unit={unit} />
        </div>
      </div>
    );
  } else if (activity.isError) {
    content = <Unavailable onRetry={() => activity.refetch()} />;
  } else {
    content = (
      <div role="status" className="grid gap-3 sm:grid-cols-4">
        <span className="sr-only">{t("app.loading")}</span>
        <Skeleton className="h-18" />
        <Skeleton className="h-18 sm:col-span-3" />
      </div>
    );
  }

  return (
    <section aria-labelledby={id} className="grid gap-2">
      <h2 id={id} className="font-medium text-muted-foreground text-sm">
        {name === undefined
          ? t("health.overview.title", { when })
          : t("health.overview.titleOne", { name, when })}
      </h2>
      {content}
    </section>
  );
}
