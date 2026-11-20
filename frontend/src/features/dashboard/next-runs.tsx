import { Link } from "@tanstack/react-router";
import { CalendarClockIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { NextRunOf } from "#/features/jobs/job-details.tsx";
import { JOBS } from "#/features/jobs/job-names.ts";
import { RecentRuns } from "#/features/runs/recent-runs.tsx";
import { DashboardCard, Loaded } from "./dashboard-card.tsx";
import { Onward } from "./onward.tsx";
import { useSchedules } from "./schedules.ts";

// When each job runs next, the soonest first: its name (to its page) and the countdown, and for
// admins how its last runs went, as the Jobs table shows them.
export function NextRuns({ admin }: { admin: boolean }) {
  const { t } = useTranslation();
  const schedules = useSchedules();
  return (
    <DashboardCard
      title={t("dashboard.nextRuns.title")}
      icon={CalendarClockIcon}
      link={<Onward to="/jobs">{t("dashboard.nextRuns.link")}</Onward>}
    >
      <Loaded query={schedules} skeleton="h-20">
        {(entries) => (
          <ul className="grid divide-y">
            {entries.map((entry) => {
              const name = t(`schedules.${entry.key}`);
              const job = JOBS[entry.key];
              return (
                <li key={entry.key} className="grid gap-1 py-2 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 text-sm">
                    <Link
                      to="/jobs/$job"
                      params={{ job }}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {name}
                    </Link>
                    {admin ? <RecentRuns job={job} name={name} /> : null}
                  </div>
                  <p className="text-muted-foreground text-xs">
                    <NextRunOf entry={entry} />
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </Loaded>
    </DashboardCard>
  );
}
