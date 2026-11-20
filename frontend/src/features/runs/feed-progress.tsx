import { cn } from "cn";
import { useTranslation } from "react-i18next";
import type { FeedOutcome, SourceCollectionProgress } from "#/client/types.gen.ts";
import type { Translate } from "#/i18n/i18n.ts";

const PERCENT = 100;

interface Shown {
  position: string; // line 1: "Feed 7 of 23"
  feed?: string; // line 2: the Feed's slug, if one is read or was read last
  activity: string[]; // line 2: what it does, or what became of it
  fraction: number; // of the whole run, the Feed being read included: 0 to 1
}

// What became of the Feed read last: "14 new", or that it failed or ran out of time.
function outcomeOf(latest: FeedOutcome, t: Translate) {
  if (latest.reason !== null) {
    return [t("jobs.feedProgress.failed", { reason: latest.reason })];
  }
  return [
    t("jobs.feedProgress.new", { count: latest.new }),
    ...(latest.out_of_time ? [t("jobs.feedProgress.outOfTime")] : []),
  ];
}

// Where the run is: before its first report, at a Feed (listing it, then item by item), or between
// two Feeds (what became of the last one).
function shownOf(progress: SourceCollectionProgress | null, t: Translate): Shown {
  if (!progress) {
    const starting = t("jobs.feedProgress.starting");
    return { position: starting, activity: [t("jobs.feedProgress.lookingUp")], fraction: 0 };
  }
  const { feeds_total: total, feeds_done: done, current, latest } = progress;
  const of = (feeds: number) => (total > 0 ? Math.min(feeds / total, 1) : 0);
  if (current) {
    const { feed, items } = current;
    const position = t("jobs.feedProgress.feed", { position: done + 1, total });
    if (items === null) {
      return { position, feed, activity: [t("jobs.feedProgress.listing")], fraction: of(done) };
    }
    return {
      position,
      feed,
      activity: [
        t("jobs.feedProgress.items", { done: current.done, count: items }),
        t("jobs.feedProgress.new", { count: current.new }),
      ],
      fraction: of(done + (items > 0 ? current.done / items : 0)),
    };
  }
  if (latest) {
    const position = t("jobs.feedProgress.feed", { position: done, total });
    return { position, feed: latest.feed, activity: outcomeOf(latest, t), fraction: of(done) };
  }
  return {
    position: t("jobs.feedProgress.total", { count: total }),
    activity: [t("jobs.feedProgress.firstFeed")],
    fraction: 0,
  };
}

// One line each, of one height, whatever it says.
const LINE = "flex h-5 min-w-0 items-baseline overflow-hidden text-sm leading-5 tabular-nums";

// How far a running Source Collection got: where it is and how much is done, the bar, and the Feed
// being read with what it does. Two lines of one height in every state, the Feed's name cut short
// with an ellipsis: the box keeps its size as the run goes from Feed to Feed. The bar moves within
// a Feed too, item by item.
export function FeedProgress({ progress }: { progress: SourceCollectionProgress | null }) {
  const { t, i18n } = useTranslation();
  const shown = shownOf(progress, t);
  const percent = Math.floor(shown.fraction * PERCENT);
  const separator = t("jobs.feedProgress.separator");
  const words = [shown.feed, ...shown.activity]
    .filter(Boolean)
    .join(t("jobs.feedProgress.wordSeparator"));
  return (
    <div className="grid w-full min-w-0 gap-1.5">
      <p className={cn(LINE, "gap-3")}>
        <span className="min-w-0 flex-1 truncate font-medium">{shown.position}</span>
        <span className="shrink-0 text-muted-foreground">
          {new Intl.NumberFormat(i18n.language, { style: "percent" }).format(percent / PERCENT)}
        </span>
      </p>
      <div
        role="progressbar"
        aria-label={t("jobs.feedProgress.label")}
        aria-valuemin={0}
        aria-valuemax={PERCENT}
        aria-valuenow={percent}
        aria-valuetext={t("jobs.feedProgress.valueText", {
          position: shown.position,
          activity: words,
        })}
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className={cn(LINE, "text-muted-foreground")}>
        {shown.feed ? (
          <>
            {/* at most 60%: what it does stays in view, cut short only on a narrow screen */}
            <span
              title={shown.feed}
              className="max-w-[60%] shrink-0 truncate font-medium text-foreground"
            >
              {shown.feed}
            </span>
            <span className="shrink-0 whitespace-pre">{separator}</span>
          </>
        ) : null}
        <span className="min-w-0 flex-1 truncate">{shown.activity.join(separator)}</span>
      </p>
    </div>
  );
}
