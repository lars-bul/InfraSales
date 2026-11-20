import { useQueryClient, useSuspenseInfiniteQuery } from "@tanstack/react-query";
import { useNavigate, useRouteContext, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { Button } from "#/components/ui/button.tsx";
import { TableBody, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { Unavailable } from "#/components/unavailable.tsx";
import { auditEventsQuery, byActor, type AuditFilters as Filters, SYSTEM } from "./audit-events.ts";
import { AuditFilters } from "./audit-filters.tsx";
import { AuditRow } from "./audit-row.tsx";
import { person } from "./sentence.ts";

const FROM = "/_signed-in/audit";

// The subjects in `events` and the chosen one, besides those already known; none if no new one.
function newPeople(known: string[], events: AuditEventRead[], chosen: string | undefined) {
  const seen = [...events.map((event) => event.actor), chosen];
  const added = new Set(
    seen.filter(
      (subject): subject is string =>
        subject !== null && subject !== undefined && subject !== SYSTEM && !known.includes(subject),
    ),
  );
  return [...added];
}

// The page's loader has read the first page; loading and failing to are the router's to show.
// Older events load on request, and a failure there is offered again in place. The filters live
// in the URL; the person filter offers everyone seen in the log since the page opened.
export function AuditLog() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { user } = useRouteContext({ from: FROM });
  const filters = useSearch({ from: FROM });
  const navigate = useNavigate({ from: "/audit" });
  const query = auditEventsQuery(filters);
  const { data, hasNextPage, fetchNextPage, isFetchingNextPage, isFetchNextPageError } =
    useSuspenseInfiniteQuery(query);
  const loaded = data.pages.flat();
  const events = byActor(loaded, filters.actor);
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "medium" });
  const loadOlder = () => fetchNextPage();

  // Everyone seen stays on offer when a filter hides them (adjusted while rendering, not after).
  const [people, setPeople] = useState<string[]>([]);
  const added = newPeople(people, loaded, filters.actor);
  if (added.length > 0) {
    const all = [...people, ...added];
    setPeople(all.sort((a, b) => person(t, a, "").localeCompare(person(t, b, ""))));
  }
  const filter = (chosen: Filters) => navigate({ search: (search) => ({ ...search, ...chosen }) });
  const filtered = filters.actor !== undefined || filters.action !== undefined;

  return (
    <div className="flex flex-col items-start gap-4">
      <div className="flex w-full flex-wrap items-end justify-between gap-4">
        <AuditFilters filters={filters} people={people} reader={user.subject} onChange={filter} />
        <Button
          variant="outline"
          onClick={() => queryClient.resetQueries({ queryKey: query.queryKey })}
        >
          {t("app.refresh")}
        </Button>
      </div>
      {events.length === 0 ? (
        <EmptyState
          className="rounded-lg border border-dashed"
          title={t(filtered ? "audit.noMatch.title" : "audit.empty.title")}
          description={t(filtered ? "audit.noMatch.description" : "audit.empty.description")}
        />
      ) : (
        <DataTable caption={t("audit.caption", { count: events.length })}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col" className="ps-12">
                {t("audit.activity")}
              </TableHead>
              <TableHead scope="col" className="text-end">
                {t("audit.time")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event) => (
              <AuditRow key={event.id} event={event} reader={user.subject} time={time} />
            ))}
          </TableBody>
        </DataTable>
      )}
      {hasNextPage && isFetchNextPageError ? <Unavailable onRetry={loadOlder} /> : null}
      {hasNextPage && !isFetchNextPageError ? (
        <p className="flex items-center gap-2">
          <Button variant="outline" onClick={loadOlder} disabled={isFetchingNextPage}>
            {t("audit.older")}
          </Button>
          <span role="status">{isFetchingNextPage ? t("app.loading") : null}</span>
        </p>
      ) : null}
    </div>
  );
}
