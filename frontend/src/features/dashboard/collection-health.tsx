import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ActivityIcon, CircleCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listFeedsOptions } from "#/client/@tanstack/react-query.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";
import { notRead, STATE_BADGES } from "#/features/feeds/states.ts";
import { RunsChart } from "#/features/jobs/runs-chart.tsx";
import { activityQuery } from "#/features/runs/run-query.ts";
import { DashboardCard, Loaded } from "./dashboard-card.tsx";
import { Onward } from "./onward.tsx";

const SHOWN = 5; // Feeds named at most; the Feeds page lists the rest

// How Source Collection's runs ended over the last 7 days: "18 runs in the last 7 days, 2
// failed" over a bar per day, as Stripe's request chart counts its total and failed.
function Runs() {
  const { t } = useTranslation();
  const activity = useQuery(activityQuery({ job: "scrape" }));
  return (
    <Loaded query={activity} skeleton="h-36">
      {({ buckets, unit }) => {
        const failed = buckets.reduce((sum, bucket) => sum + bucket.failed, 0);
        const runs = buckets.reduce((sum, bucket) => sum + bucket.succeeded, failed);
        return (
          <div className="grid gap-2">
            <p className="flex flex-wrap gap-x-3 text-sm">
              <span>{t("dashboard.health.runs", { count: runs })}</span>
              <span className={failed > 0 ? "text-destructive" : "text-muted-foreground"}>
                {t("dashboard.health.failed", { count: failed })}
              </span>
            </p>
            <RunsChart buckets={buckets} unit={unit} />
          </div>
        );
      }}
    </Loaded>
  );
}

// The Feeds the last collection could not read, each with why and leading to itself among the
// Feeds that need attention; while every Feed was read, one calm line says so (as Stripe's "running smoothly"),
// so a healthy collection reads quiet.
function Feeds() {
  const { t } = useTranslation();
  const feeds = useQuery(listFeedsOptions());
  return (
    <Loaded query={feeds}>
      {(all) => {
        const failing = notRead(all);
        if (failing.length === 0) {
          return (
            <p className="flex items-center gap-2 text-muted-foreground text-sm">
              <CircleCheck aria-hidden={true} className="size-4 text-success" />
              {t("dashboard.health.smooth")}
            </p>
          );
        }
        return (
          <div className="grid gap-1">
            <h3 className="text-muted-foreground text-xs">{t("dashboard.health.notRead")}</h3>
            <ul className="grid divide-y">
              {failing.slice(0, SHOWN).map((feed) => (
                <li key={feed.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <Link
                    to="/feeds"
                    search={{ view: "attention", q: feed.name }}
                    className="truncate underline-offset-4 hover:underline"
                  >
                    {feed.name}
                  </Link>
                  <Badge variant={STATE_BADGES[feed.state]}>
                    {t(`feeds.states.${feed.state}`)}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        );
      }}
    </Loaded>
  );
}

// Whether Source Collection is healthy (admins): its runs over the week and the Feeds it could
// not read, leading on to its runs.
export function CollectionHealth({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <DashboardCard
      title={t("dashboard.health.title")}
      icon={ActivityIcon}
      className={className}
      link={
        <Onward to="/runs" search={{ job: "scrape" }}>
          {t("dashboard.health.link")}
        </Onward>
      }
    >
      <Runs />
      <Feeds />
    </DashboardCard>
  );
}
