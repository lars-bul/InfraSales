import { useQuery } from "@tanstack/react-query";
import { Link, type LinkComponentProps } from "@tanstack/react-router";
import { NewspaperIcon, RssIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { listFeedsOptions } from "#/client/@tanstack/react-query.gen.ts";
import { notRead } from "#/features/feeds/states.ts";
import { lastCollectionQuery } from "#/features/runs/run-query.ts";
import { ago } from "#/lib/ago.ts";
import { Loaded } from "./dashboard-card.tsx";

interface StageProps {
  name: string;
  icon: typeof RssIcon;
  link: LinkComponentProps;
  children: ReactNode;
}

// One stage of the strip: its name (to its page) over its figure and a line about it.
function Stage({ name, icon: Icon, link, children }: StageProps) {
  return (
    <li className="grid content-start gap-1 p-4">
      <Link
        {...link}
        className="flex items-center gap-2 justify-self-start text-muted-foreground text-xs underline-offset-4 hover:text-foreground hover:underline"
      >
        <Icon aria-hidden={true} className="size-3.5" />
        {name}
      </Link>
      {children}
    </li>
  );
}

function Figure({ value, children }: { value: ReactNode; children: ReactNode }) {
  return (
    <>
      <p className="font-medium text-2xl tabular-nums">{value}</p>
      <p className="text-muted-foreground text-xs">{children}</p>
    </>
  );
}

// How many Feeds there are, and how many the last collection could not read (red while any).
function FeedsStage() {
  const { t } = useTranslation();
  const feeds = useQuery(listFeedsOptions());
  return (
    <Stage name={t("feeds.title")} icon={RssIcon} link={{ to: "/feeds" }}>
      <Loaded query={feeds}>
        {(all) => {
          const failing = notRead(all).length;
          let line: ReactNode = t("dashboard.stages.feeds.allRead");
          if (all.length === 0) {
            line = t("dashboard.stages.feeds.none");
          } else if (failing > 0) {
            line = (
              <span className="text-destructive">
                {t("dashboard.stages.feeds.unread", { count: failing })}
              </span>
            );
          }
          return <Figure value={all.length}>{line}</Figure>;
        }}
      </Loaded>
    </Stage>
  );
}

// How many new Source Versions the last collection found, and how long ago.
function SourcesStage() {
  const { t, i18n } = useTranslation();
  const last = useQuery(lastCollectionQuery());
  return (
    <Stage name={t("sources.title")} icon={NewspaperIcon} link={{ to: "/sources" }}>
      <Loaded query={last}>
        {([run]) => {
          if (!run?.result) {
            return <Figure value="–">{t("dashboard.stages.sources.none")}</Figure>;
          }
          const when = ago(run.finished_at ?? run.scheduled_for, i18n.language);
          return (
            <Figure value={run.result.versions_new}>
              {t("dashboard.stages.sources.versions", { count: run.result.versions_new, when })}
            </Figure>
          );
        }}
      </Loaded>
    </Stage>
  );
}

// Collecting at a glance, as Jobber's workflow strip: Feeds → Sources, each stage's figure
// leading to its page. The stages that read what was collected follow (ADR 06 §5). Admins only:
// viewers may not open these pages.
export function Pipeline() {
  const { t } = useTranslation();
  return (
    <ol
      aria-label={t("dashboard.pipeline")}
      className="grid divide-y rounded-xl bg-card ring-1 ring-foreground/10 sm:grid-flow-col sm:auto-cols-fr sm:divide-x sm:divide-y-0"
    >
      <FeedsStage />
      <SourcesStage />
    </ol>
  );
}
