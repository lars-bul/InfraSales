import { useQuery } from "@tanstack/react-query";
import { MinusIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listJobRunsOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { JobName } from "#/client/types.gen.ts";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { StatusIcon } from "./run-row.tsx";

const COUNT = 5; // as Databricks' job list shows them

interface Props {
  job: JobName;
  name: string; // the job's display name
}

// A job's last runs as a row of status icons, oldest first, the newest at the end: each says how
// the run went and when it was due. Places without a run yet show a dash.
export function RecentRuns({ job, name }: Props) {
  const { t, i18n } = useTranslation();
  const recent = useQuery(listJobRunsOptions({ query: { job, limit: COUNT } }));

  if (recent.isError) {
    return <span className="text-muted-foreground">{t("history.recent.unavailable")}</span>;
  }
  if (!recent.isSuccess) {
    return (
      <div role="status">
        <span className="sr-only">{t("app.loading")}</span>
        <Skeleton className="h-4 w-24" />
      </div>
    );
  }
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  const runs = recent.data.slice(0, COUNT).reverse();
  const missing = Array.from({ length: COUNT - runs.length }, (_, place) => place);
  return (
    <ol aria-label={t("history.recent.label", { name })} className="flex items-center gap-1">
      {missing.map((place) => (
        <li key={place}>
          <MinusIcon
            role="img"
            aria-label={t("history.recent.none")}
            className="size-4 text-muted-foreground/60"
          />
        </li>
      ))}
      {runs.map((run) => {
        const label = t("history.recent.run", {
          status: t(`history.statuses.${run.status}`),
          time: time.format(new Date(run.scheduled_for)),
        });
        return (
          <li key={run.id}>
            <StatusIcon status={run.status} label={label} />
          </li>
        );
      })}
    </ol>
  );
}
