import { useInfiniteQuery } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { RunHistoryEntry } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Button } from "#/components/ui/button.tsx";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { TableBody, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { type RunFilters, runsQuery } from "./run-query.ts";
import { RunRow } from "./run-row.tsx";

interface Props {
  filters: RunFilters;
  name?: string | undefined; // the one job's display name: its runs only, no Job column
}

// The runs loaded so far. Every job's runs name their job; the Result column summarises Source
// Collection's results, the only ones with a type so far.
function RunTable({ runs, name }: Props & { runs: RunHistoryEntry[] }) {
  const { t, i18n } = useTranslation();
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  const withJob = name === undefined;
  const caption = withJob
    ? t("history.captionAll", { count: runs.length })
    : t("history.caption", { count: runs.length, name });
  return (
    <DataTable caption={caption}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("history.scheduled")}</TableHead>
          {withJob ? <TableHead scope="col">{t("history.job")}</TableHead> : null}
          <TableHead scope="col">{t("history.trigger")}</TableHead>
          <TableHead scope="col">{t("history.status")}</TableHead>
          <TableHead scope="col">{t("history.result")}</TableHead>
          <TableHead scope="col">{t("history.attempts")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <RunRow key={run.id} run={run} withJob={withJob} withResult={true} time={time} />
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
      <Skeleton className="h-6 w-full" />
      <Skeleton className="h-6 w-full" />
    </div>
  );
}

// Filters beyond the page's own job: none of the runs may match them.
function narrowed({ filters, name }: Props): boolean {
  return (
    filters.status !== undefined ||
    filters.trigger !== undefined ||
    filters.start !== undefined ||
    filters.end !== undefined ||
    (name === undefined && filters.job !== undefined)
  );
}

interface OlderProps {
  name: string | undefined;
  failed: boolean; // the last try to load them failed
  fetching: boolean;
  onMore: () => void;
}

// Below the runs: older ones on request, or, if they failed to load, a try again.
function OlderRuns({ name, failed, fetching, onMore }: OlderProps) {
  const { t } = useTranslation();
  if (failed) {
    return <Unavailable onRetry={onMore} />;
  }
  return (
    <p className="flex items-center gap-3">
      <Button variant="outline" onClick={onMore} disabled={fetching}>
        {name === undefined ? t("history.olderAll") : t("history.older", { name })}
      </Button>
      <span role="status">{fetching ? t("app.loading") : null}</span>
    </p>
  );
}

// Recent runs (admins), newest first: of one job on its page, or of every job, as filtered, on
// the Job runs page. How each went, who started it, what it did, and why one failed. Older runs
// load on request.
export function RunHistory({ filters, name }: Props) {
  const { t } = useTranslation();
  const history = useInfiniteQuery(runsQuery(filters));
  // Shown while older runs fail to load, too: they can be tried again below them.
  const runs =
    history.isSuccess || history.isFetchNextPageError ? history.data.pages.flat() : undefined;
  const empty = narrowed({ filters, name }) ? "noMatch" : "empty";

  return (
    <div className="grid gap-2">
      {runs ? (
        <Button
          variant="outline"
          size="sm"
          className="justify-self-end"
          onClick={() => history.refetch()}
        >
          <RotateCw aria-hidden={true} data-icon="inline-start" />
          {t("app.refresh")}
        </Button>
      ) : null}
      {history.status === "pending" ? <Loading /> : null}
      {history.isError && !history.isFetchNextPageError ? (
        <Unavailable onRetry={() => history.refetch()} />
      ) : null}
      {runs?.length === 0 ? (
        <EmptyState
          title={t(`history.${empty}.title`)}
          description={t(`history.${empty}.description`)}
          className="rounded-lg border border-dashed"
        />
      ) : null}
      {runs && runs.length > 0 ? <RunTable runs={runs} filters={filters} name={name} /> : null}
      {history.hasNextPage || history.isFetchNextPageError ? (
        <OlderRuns
          name={name}
          failed={history.isFetchNextPageError}
          fetching={history.isFetchingNextPage}
          onMore={() => history.fetchNextPage()}
        />
      ) : null}
    </div>
  );
}
