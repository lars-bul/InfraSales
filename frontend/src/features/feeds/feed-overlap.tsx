import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { readFeedOverlapOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { FeedPair, FeedShare } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Label } from "#/components/ui/label.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";

// The windows to count over, in days.
const WEEK = 7;
const TWO_WEEKS = 14; // the API's default
const MONTH = 30;
const QUARTER = 90; // the API's longest
const WINDOWS = [WEEK, TWO_WEEKS, MONTH, QUARTER] as const;
type Days = (typeof WINDOWS)[number];

type NameOf = (slug: string) => string;

function Window({ days, onChange }: { days: Days; onChange: (days: Days) => void }) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{t("feeds.overlap.window")}</Label>
      <NativeSelect
        id={id}
        value={days}
        onChange={(event) => onChange(Number(event.target.value) as Days)}
      >
        {WINDOWS.map((window) => (
          <NativeSelectOption key={window} value={window}>
            {t("feeds.overlap.days", { count: window })}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </div>
  );
}

// The own share written out, with a bar that only repeats it; nothing listed: says so.
function OwnShare({ share }: { share: number | null }) {
  const { t, i18n } = useTranslation();
  if (share === null) {
    return <span className="text-muted-foreground">{t("feeds.overlap.shares.nothing")}</span>;
  }
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent" });
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span aria-hidden={true} className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <span
          className="block h-full origin-left bg-primary rtl:origin-right"
          style={{ transform: `scaleX(${share})` }}
        />
      </span>
      <span className="w-10 tabular-nums">{percent.format(share)}</span>
    </span>
  );
}

// Each Feed's listings and how many of them another Feed lists too, the least own share first:
// the Feeds that add least of their own lead.
function Shares({ feeds, nameOf }: { feeds: FeedShare[]; nameOf: NameOf }) {
  const { t } = useTranslation();
  return (
    <DataTable caption={t("feeds.overlap.shares.caption", { count: feeds.length })}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("feeds.overlap.shares.feed")}</TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.overlap.shares.runs")}
          </TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.overlap.shares.listings")}
          </TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.overlap.shares.shared")}
          </TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.overlap.shares.own")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {feeds.map((feed) => (
          <TableRow key={feed.feed}>
            <TableHead scope="row" className="font-medium text-foreground">
              {nameOf(feed.feed)}
            </TableHead>
            <TableCell className="text-end tabular-nums">{feed.runs}</TableCell>
            <TableCell className="text-end tabular-nums">{feed.own + feed.shared}</TableCell>
            <TableCell className="text-end tabular-nums">{feed.shared}</TableCell>
            <TableCell className="text-end">
              <OwnShare share={feed.own_share} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </DataTable>
  );
}

// The pairs of Feeds listing the most addresses both list, most first.
function Pairs({ pairs, nameOf }: { pairs: FeedPair[]; nameOf: NameOf }) {
  const { t } = useTranslation();
  if (pairs.length === 0) {
    return (
      <EmptyState
        title={t("feeds.overlap.pairs.none.title")}
        description={t("feeds.overlap.pairs.none.description")}
        className="rounded-lg border border-dashed"
      />
    );
  }
  return (
    <DataTable caption={t("feeds.overlap.pairs.caption", { count: pairs.length })}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("feeds.overlap.pairs.feeds")}</TableHead>
          <TableHead scope="col" className="text-end">
            {t("feeds.overlap.pairs.listings")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {pairs.map((pair) => (
          <TableRow key={`${pair.feed} ${pair.other}`}>
            <TableHead scope="row" className="font-medium text-foreground">
              {t("feeds.overlap.pairs.pair", {
                feed: nameOf(pair.feed),
                other: nameOf(pair.other),
              })}
            </TableHead>
            <TableCell className="text-end tabular-nums">{pair.listings}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </DataTable>
  );
}

// Which Feeds list the same documents (admins), over the Source Collection runs of the window
// chosen: what each Feed adds of its own, and the pairs that overlap most. Every number is
// written out. While another window is read, the last one stays, dimmed and busy, and a status
// says so. `names` names the Feeds by slug; a Feed gone shows its slug.
export function FeedOverlap({ names }: { names: ReadonlyMap<string, string> }) {
  const { t } = useTranslation();
  const [days, setDays] = useState<Days>(TWO_WEEKS);
  const overlap = useQuery({
    ...readFeedOverlapOptions({ query: { days } }),
    placeholderData: keepPreviousData, // a new window keeps the last one shown until it is read
  });
  const nameOf = (slug: string) => names.get(slug) ?? slug;
  const counting = overlap.data !== undefined && overlap.data.days !== days; // the last window's

  let shown: ReactNode;
  if (overlap.isSuccess) {
    const { runs, feeds, pairs } = overlap.data;
    shown =
      runs === 0 ? (
        <EmptyState
          title={t("feeds.overlap.empty.title")}
          description={t("feeds.overlap.empty.description")}
          className="rounded-lg border border-dashed"
        />
      ) : (
        <>
          <p className="text-muted-foreground text-sm">
            {t("feeds.overlap.runs", { count: runs })}
          </p>
          <Shares feeds={feeds} nameOf={nameOf} />
          <Pairs pairs={pairs} nameOf={nameOf} />
        </>
      );
  } else if (overlap.isError) {
    shown = <Unavailable onRetry={() => overlap.refetch()} />;
  } else {
    shown = (
      <div role="status" className="grid gap-3">
        <span className="sr-only">{t("app.loading")}</span>
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-prose text-muted-foreground text-sm">
          {t("feeds.overlap.description")}
        </p>
        <Window days={days} onChange={setDays} />
      </div>
      <p role="status" className="text-muted-foreground text-sm empty:sr-only">
        {counting ? t("feeds.overlap.counting", { count: days }) : null}
      </p>
      <div aria-busy={counting} className={cn("grid gap-4", counting && "opacity-60")}>
        {shown}
      </div>
    </div>
  );
}
