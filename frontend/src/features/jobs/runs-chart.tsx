import { useTranslation } from "react-i18next";
import type { BucketCounts, RunActivity } from "#/client/types.gen.ts";

const HEIGHT = 40; // the chart's drawing units: a bar per hour or day, gaps between them
const BAR = 10;
const GAP = 3;
const BASELINE = 1; // a bucket without runs still shows its place

type Unit = RunActivity["unit"];

// Where a bucket begins, as the browser's time zone names it (the API counted in it): a day
// "Fri, Oct 16", an hour "Fri, Oct 16, 10 AM".
function bucketLabel(start: string, unit: Unit, language: string): string {
  return new Intl.DateTimeFormat(language, {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(unit === "hour" && { hour: "numeric" }),
  }).format(new Date(start));
}

// Runs per hour or per day as stacked bars, succeeded below failed, the first and last bucket
// named under them (as Databricks' run chart has its time axis). The bars are drawn with SVG
// attributes (no inline styles, which the CSP forbids); a visually hidden table says the same
// for screen readers, so the picture itself is hidden from them.
export function RunsChart({ buckets, unit }: { buckets: BucketCounts[]; unit: Unit }) {
  const { t, i18n } = useTranslation();
  const most = Math.max(1, ...buckets.map((bucket) => bucket.succeeded + bucket.failed));
  const scale = (count: number) => (count / most) * HEIGHT;
  const width = buckets.length * (BAR + GAP) - GAP;
  const label = (bucket: BucketCounts | undefined) =>
    bucket ? bucketLabel(bucket.start, unit, i18n.language) : null;

  return (
    <>
      <svg
        aria-hidden="true"
        viewBox={`0 0 ${width} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-28 w-full"
      >
        {buckets.map((bucket, index) => {
          const x = index * (BAR + GAP);
          const succeeded = scale(bucket.succeeded);
          const failed = scale(bucket.failed);
          return bucket.succeeded + bucket.failed === 0 ? (
            <rect
              key={bucket.start}
              x={x}
              y={HEIGHT - BASELINE}
              width={BAR}
              height={BASELINE}
              className="fill-muted-foreground/40"
            />
          ) : (
            <g key={bucket.start}>
              <rect
                x={x}
                y={HEIGHT - succeeded}
                width={BAR}
                height={succeeded}
                className="fill-success"
              />
              <rect
                x={x}
                y={HEIGHT - succeeded - failed}
                width={BAR}
                height={failed}
                className="fill-destructive"
              />
            </g>
          );
        })}
      </svg>
      <p aria-hidden="true" className="flex justify-between gap-3 text-muted-foreground text-xs">
        <span>{label(buckets[0])}</span>
        <span>{buckets.length > 1 ? label(buckets.at(-1)) : null}</span>
      </p>
      <p aria-hidden="true" className="flex gap-3 text-muted-foreground text-xs">
        <span className="flex items-center gap-1">
          <span className="size-2 rounded-xs bg-success" />
          {t("health.succeeded")}
        </span>
        <span className="flex items-center gap-1">
          <span className="size-2 rounded-xs bg-destructive" />
          {t("health.failed")}
        </span>
      </p>
      <table className="sr-only">
        <caption>
          {t(unit === "hour" ? "health.overview.perHour" : "health.overview.perDay")}
        </caption>
        <thead>
          <tr>
            <th scope="col">
              {t(unit === "hour" ? "health.overview.hour" : "health.overview.day")}
            </th>
            <th scope="col">{t("health.succeeded")}</th>
            <th scope="col">{t("health.failed")}</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((bucket) => (
            <tr key={bucket.start}>
              <th scope="row">{label(bucket)}</th>
              <td>{bucket.succeeded}</td>
              <td>{bucket.failed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
