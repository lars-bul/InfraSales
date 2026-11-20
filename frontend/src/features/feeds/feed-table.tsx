import { Link } from "@tanstack/react-router";
import { cn } from "cn";
import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import type { FeedCategory, FeedKind, FeedRead, FeedState } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import type { Translate } from "#/i18n/i18n.ts";
import { ago } from "#/lib/ago.ts";
import { DeleteFeed } from "./delete-feed.tsx";
import { type FeedGroup, groupedBy, isStale } from "./feed-filters.ts";
import { KINDS } from "./kinds.ts";
import { STATE_DOTS } from "./states.ts";

const SCHEME = /^https?:\/\//;
const COLUMNS = 7; // a group's heading spans the table

// When the Feed was last read, as relative time ("3 hours ago"), the exact time on hover; amber
// once a Feed that is on has not been read for a day.
function LastRead({ feed, now }: { feed: FeedRead; now: Date }) {
  const { t, i18n } = useTranslation();
  const stale = isStale(feed, now) && "text-warning";
  if (!feed.last_scraped_at) {
    return <span className={cn(stale)}>{t("feeds.never")}</span>;
  }
  const exact = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <time
      dateTime={feed.last_scraped_at}
      title={exact.format(new Date(feed.last_scraped_at))}
      className={cn(stale)}
    >
      {ago(feed.last_scraped_at, i18n.language)}
    </time>
  );
}

// The Feed's name, its address below it without the scheme, and below that why it fails. A
// blocked Feed says what that means: a person decides, nobody works around a bot wall (ADR 03 §6).
function FeedName({ feed }: { feed: FeedRead }) {
  const { t } = useTranslation();
  const reason = feed.state === "blocked" ? t("feeds.blocked") : feed.last_error;
  return (
    <div className="grid max-w-md gap-0.5">
      <span className="font-medium">{feed.name}</span>
      <span title={feed.url} className="truncate text-muted-foreground text-xs">
        {feed.url.replace(SCHEME, "")}
      </span>
      {feed.state !== "ok" && reason ? (
        <span
          className={cn(
            "whitespace-normal text-xs",
            feed.state === "blocked" ? "text-warning" : "text-destructive",
          )}
        >
          {reason}
        </span>
      ) : null}
    </div>
  );
}

// The state as a coloured dot and its name; a Feed switched off has a grey dot and says so.
function FeedStatus({ feed }: { feed: FeedRead }) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-0.5">
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden={true}
          className={cn(
            "size-2 shrink-0 rounded-full",
            feed.enabled ? STATE_DOTS[feed.state] : "bg-muted-foreground/50",
          )}
        />
        {t(`feeds.states.${feed.state}`)}
      </span>
      {feed.enabled ? null : (
        <span className="ps-3.5 text-muted-foreground text-xs">{t("feeds.disabled")}</span>
      )}
    </div>
  );
}

// How many Sources the Feed has collected, leading to them; none: a plain 0.
function SourceCount({ feed }: { feed: FeedRead }) {
  const { t, i18n } = useTranslation();
  const count = new Intl.NumberFormat(i18n.language).format(feed.sources);
  if (feed.sources === 0) {
    return <span className="text-muted-foreground">{count}</span>;
  }
  return (
    <Link
      to="/sources"
      search={{ feed: feed.slug }}
      aria-label={t("feeds.linked", { count: feed.sources, name: feed.name })}
      className="text-primary underline-offset-4 hover:underline"
    >
      {count}
    </Link>
  );
}

interface RowProps {
  feed: FeedRead;
  now: Date;
  focusAfter: RefObject<HTMLElement | null>; // once a Feed is deleted
  onDeleted: (feed: FeedRead) => void;
}

// One Feed: name and address, state, kind, category, Sources, last read; a Feed that has
// collected no Sources yet may be deleted from it.
function FeedRow({ feed, now, focusAfter, onDeleted }: RowProps) {
  const { t } = useTranslation();
  return (
    <TableRow className="[&>td]:align-top">
      <TableCell>
        <FeedName feed={feed} />
      </TableCell>
      <TableCell>
        <FeedStatus feed={feed} />
      </TableCell>
      <TableCell>{t(`feeds.kinds.${KINDS[feed.kind]}`)}</TableCell>
      <TableCell>{t(`feeds.categories.${feed.category}`)}</TableCell>
      <TableCell className="text-end tabular-nums">
        <SourceCount feed={feed} />
      </TableCell>
      <TableCell>
        <LastRead feed={feed} now={now} />
      </TableCell>
      <TableCell className="py-1.5 text-end">
        {feed.has_sources ? null : (
          <DeleteFeed feed={feed} focusAfter={focusAfter} onDeleted={onDeleted} />
        )}
      </TableCell>
    </TableRow>
  );
}

// A group's heading: the category, state or kind its Feeds share.
function groupName(group: FeedGroup, value: string, t: Translate): string {
  if (group === "kind") {
    return t(`feeds.kinds.${KINDS[value as FeedKind]}`);
  }
  return group === "state"
    ? t(`feeds.states.${value as FeedState}`)
    : t(`feeds.categories.${value as FeedCategory}`);
}

interface Props {
  shown: FeedRead[];
  group?: FeedGroup | undefined; // under their categories, states or kinds
  count: string;
  now: Date; // which Feeds are stale
  focusAfter: RefObject<HTMLElement | null>;
  onDeleted: (feed: FeedRead) => void;
}

/**
 * The Feeds left, a row each, as a table captioned with how many they are; grouped, each
 * category, state or kind heads its own Feeds, with how many they are.
 */
export function FeedTable({ shown, group, count, now, focusAfter, onDeleted }: Props) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const row = (feed: FeedRead) => (
    <FeedRow key={feed.id} feed={feed} now={now} focusAfter={focusAfter} onDeleted={onDeleted} />
  );
  return (
    <DataTable caption={count}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("feeds.name")}</TableHead>
          <TableHead scope="col">{t("feeds.state")}</TableHead>
          <TableHead scope="col">{t("feeds.kind")}</TableHead>
          <TableHead scope="col">{t("feeds.category")}</TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.sources")}
          </TableHead>
          <TableHead scope="col">{t("feeds.lastRead")}</TableHead>
          <TableHead scope="col">
            <span className="sr-only">{t("feeds.actions")}</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      {group ? (
        groupedBy(shown, group).map(({ value, feeds }) => (
          <TableBody key={value}>
            <TableRow className="hover:bg-transparent">
              <TableHead scope="rowgroup" colSpan={COLUMNS} className="h-8 bg-muted/30">
                {groupName(group, value, t)}{" "}
                <span className="tabular-nums">{number.format(feeds.length)}</span>
              </TableHead>
            </TableRow>
            {feeds.map(row)}
          </TableBody>
        ))
      ) : (
        <TableBody>{shown.map(row)}</TableBody>
      )}
    </DataTable>
  );
}
