import { cn } from "cn";
import { CircleCheck, CircleX, Clock, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { FeedOutcome } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import type { Translate } from "#/i18n/i18n.ts";

type Outcome = "read" | "failed" | "outOfTime";

// Each outcome as an icon and a word in its colour, so it never rests on colour alone.
const OUTCOMES = {
  read: { icon: CircleCheck, colour: "text-success" },
  failed: { icon: CircleX, colour: "text-destructive" },
  outOfTime: { icon: Clock, colour: "text-warning" },
} as const satisfies Record<Outcome, { icon: LucideIcon; colour: string }>;

// What became of the items each Feed listed, as the run counted them.
const COUNTS = ["items", "new", "unchanged", "known", "seen", "failed"] as const;

// How the Feed went, and in words: "Read", "Failed: http 404" or "Out of time: 2 left".
function outcomeOf(feed: FeedOutcome, t: Translate): [Outcome, string] {
  if (feed.reason !== null) {
    return ["failed", t("history.feeds.outcomes.failed", { reason: feed.reason })];
  }
  if (!feed.out_of_time) {
    return ["read", t("history.feeds.outcomes.read")];
  }
  return [
    "outOfTime",
    feed.unread === null
      ? t("history.feeds.outcomes.notListed")
      : t("history.feeds.outcomes.outOfTime", { count: feed.unread }),
  ];
}

// Under the outcome, the other sites whose bot wall kept some of its documents out, if any.
function OutcomeCell({ feed }: { feed: FeedOutcome }) {
  const { t, i18n } = useTranslation();
  const [outcome, words] = outcomeOf(feed, t);
  const { icon: Icon, colour } = OUTCOMES[outcome];
  const walled = feed.walled ?? [];
  const sites = new Intl.ListFormat(i18n.language, { type: "conjunction" }).format(walled);
  return (
    <TableCell>
      <span className={cn("inline-flex items-center gap-1.5 font-medium", colour)}>
        <Icon aria-hidden="true" className="size-4" />
        {words}
      </span>
      {walled.length > 0 && (
        <p className="text-muted-foreground text-xs">{t("history.feeds.walled", { sites })}</p>
      )}
    </TableCell>
  );
}

// What a Source Collection run did, Feed by Feed in the order it read them: how each went, what
// became of the items it listed, and how long it took.
export function FeedOutcomes({ feeds }: { feeds: FeedOutcome[] }) {
  const { t, i18n } = useTranslation();
  const seconds = new Intl.NumberFormat(i18n.language, {
    style: "unit",
    unit: "second",
    unitDisplay: "narrow",
    maximumFractionDigits: 1,
  });
  return (
    <DataTable caption={t("history.feeds.caption", { count: feeds.length })}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("history.feeds.feed")}</TableHead>
          <TableHead scope="col">{t("history.feeds.outcome")}</TableHead>
          {COUNTS.map((count) => (
            <TableHead key={count} scope="col" className="text-end">
              {t(`history.feeds.${count}`)}
            </TableHead>
          ))}
          <TableHead scope="col" className="text-end">
            {t("history.feeds.seconds")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {feeds.map((feed) => (
          <TableRow key={feed.feed}>
            <TableHead scope="row" className="font-medium text-foreground text-sm">
              {feed.feed}
            </TableHead>
            <OutcomeCell feed={feed} />
            {COUNTS.map((count) => (
              <TableCell key={count} className="text-end tabular-nums">
                {feed[count]}
              </TableCell>
            ))}
            <TableCell className="text-end tabular-nums">{seconds.format(feed.seconds)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </DataTable>
  );
}
