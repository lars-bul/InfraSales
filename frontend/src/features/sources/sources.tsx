import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { RotateCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { SourceListed } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Badge } from "#/components/ui/badge.tsx";
import { Button } from "#/components/ui/button.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { SourceFilters } from "./source-filters.tsx";
import {
  countsBack,
  hostOf,
  isNarrowed,
  type SourceSearch,
  shortUrl,
  sourceCountQuery,
  sourceParams,
  sourcesQuery,
} from "./source-query.ts";

const FROM = "/_signed-in/sources/";

// The letter a Source's host starts with, in a square: a mark to scan by, fetched from nowhere
// (a favicon service would learn every site InfraSales reads).
function HostMark({ host }: { host: string }) {
  return (
    <span
      aria-hidden={true}
      className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-muted font-medium text-muted-foreground text-xs uppercase"
    >
      {host.charAt(0)}
    </span>
  );
}

// A Source: its title (else its address) leading to its page, its host below, and whether the
// listed version is partial. Narrowed to a run, whether the run found it new or changed.
function SourceRow({
  source,
  run,
  time,
}: {
  source: SourceListed;
  run: boolean;
  time: Intl.DateTimeFormat;
}) {
  const { t } = useTranslation();
  const { version } = source;
  const host = hostOf(source.url);
  return (
    <TableRow>
      <TableCell className="whitespace-normal">
        <div className="flex items-start gap-3">
          <HostMark host={host} />
          <div className="grid min-w-0 gap-0.5">
            <Link
              to="/sources/$sourceId"
              params={{ sourceId: source.id }}
              search={{ v: version.number }}
              className="line-clamp-2 font-medium underline-offset-4 hover:underline"
            >
              {version.title ?? shortUrl(source.url)}
            </Link>
            <span className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
              {host}
              {version.partial ? <Badge variant="warning">{t("sources.partial")}</Badge> : null}
            </span>
          </div>
        </div>
      </TableCell>
      <TableCell>{version.feed.name}</TableCell>
      <TableCell>
        <span className="flex items-center gap-2">
          {source.versions}
          {run ? (
            <Badge variant={version.number === 1 ? "success" : "outline"}>
              {t(version.number === 1 ? "sources.new" : "sources.updated")}
            </Badge>
          ) : null}
        </span>
      </TableCell>
      <TableCell>
        <time dateTime={version.fetched_at}>{time.format(new Date(version.fetched_at))}</time>
      </TableCell>
    </TableRow>
  );
}

function SourceTable({ sources, run }: { sources: SourceListed[]; run: boolean }) {
  const { t, i18n } = useTranslation();
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <DataTable caption={t("sources.caption", { count: sources.length })}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("sources.source")}</TableHead>
          <TableHead scope="col">{t("sources.feed")}</TableHead>
          <TableHead scope="col">{t("sources.versions")}</TableHead>
          <TableHead scope="col">{t("sources.lastChange")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sources.map((source) => (
          <SourceRow key={source.version.id} source={source} run={run} time={time} />
        ))}
      </TableBody>
    </DataTable>
  );
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-2">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

// Below the Sources: older ones on request, or, if they failed to load, a try again.
function OlderSources({
  failed,
  fetching,
  onMore,
}: {
  failed: boolean;
  fetching: boolean;
  onMore: () => void;
}) {
  const { t } = useTranslation();
  if (failed) {
    return <Unavailable onRetry={onMore} />;
  }
  return (
    <p className="flex items-center gap-3">
      <Button variant="outline" onClick={onMore} disabled={fetching}>
        {t("sources.older")}
      </Button>
      <span role="status">{fetching ? t("app.loading") : null}</span>
    </p>
  );
}

// The moment a period counted back from now ("last 7 days") is counted from: when the filters
// last changed, or the list was refreshed. It stays put between renders, and so do the queries.
function useNow(search: SourceSearch) {
  const key = JSON.stringify(search);
  const [now, setNow] = useState(() => ({ key, at: new Date() }));
  if (now.key !== key) {
    setNow({ key, at: new Date() });
  }
  return { now: now.at, renew: () => setNow({ key, at: new Date() }) };
}

// How many Sources there are, or, narrowed, how many of them match: "1,171 Sources", "34 of
// 1,171 Sources". Nothing until the service has counted; the last count while it counts anew.
function useCount(search: SourceSearch, now: Date) {
  const { t, i18n } = useTranslation();
  const narrowed = isNarrowed(search);
  const shown = useQuery({
    ...sourceCountQuery(sourceParams(search, now)),
    placeholderData: (previous) => previous,
  });
  const total = useQuery(sourceCountQuery({})); // the same query as `shown` when nothing narrows
  const number = new Intl.NumberFormat(i18n.language);
  const refetch = {
    shown: () => shown.refetch(),
    total: () => (narrowed ? total.refetch() : undefined),
  };
  if (!(shown.data && total.data)) {
    return { text: undefined, refetch };
  }
  const { count } = total.data;
  const options = { count, total: number.format(count), shown: number.format(shown.data.count) };
  return { text: t(narrowed ? "sources.filtered" : "sources.count", options), refetch };
}

// Every Source InfraSales collected (admins), the newest change first: a search and filters (Feed,
// category, last change, changed, partial, run) narrow them, kept in the URL (`?feed=a,b&period=7d`),
// so a run's details and a Feed can link here. Above them, how many match. Each Source leads to
// its page with its versions. Older Sources load on request.
export function Sources() {
  const { t } = useTranslation();
  const search = useSearch({ from: FROM });
  const navigate = useNavigate({ from: "/sources/" });
  const change = (changes: Partial<SourceSearch>) =>
    navigate({ search: (prev) => ({ ...prev, ...changes }), replace: true });
  const { now, renew } = useNow(search);
  const listing = useInfiniteQuery(sourcesQuery(sourceParams(search, now)));
  const count = useCount(search, now);
  // A period counted back from now moves on: refreshed, it counts from the new now (and so is
  // asked for anew).
  const refresh = () => {
    count.refetch.total();
    if (countsBack(search)) {
      renew();
    } else {
      listing.refetch();
      count.refetch.shown();
    }
  };
  // Shown while older ones fail to load, too: they can be tried again below them.
  const sources =
    listing.isSuccess || listing.isFetchNextPageError ? listing.data.pages.flat() : undefined;
  const empty = isNarrowed(search) ? "noMatch" : "empty";

  return (
    <div className="grid gap-4">
      <SourceFilters
        search={search}
        onChange={change}
        count={count.text}
        actions={
          sources ? (
            <Button variant="outline" size="sm" onClick={refresh}>
              <RotateCw aria-hidden={true} data-icon="inline-start" />
              {t("app.refresh")}
            </Button>
          ) : null
        }
      />
      {listing.status === "pending" ? <Loading /> : null}
      {listing.isError && !listing.isFetchNextPageError ? (
        <Unavailable onRetry={() => listing.refetch()} />
      ) : null}
      {sources?.length === 0 ? (
        <EmptyState
          title={t(`sources.${empty}.title`)}
          description={t(`sources.${empty}.description`)}
          className="rounded-lg border border-dashed"
        />
      ) : null}
      {sources && sources.length > 0 ? (
        <SourceTable sources={sources} run={search.run !== undefined} />
      ) : null}
      {listing.hasNextPage || listing.isFetchNextPageError ? (
        <OlderSources
          failed={listing.isFetchNextPageError}
          fetching={listing.isFetchingNextPage}
          onMore={() => listing.fetchNextPage()}
        />
      ) : null}
    </div>
  );
}
