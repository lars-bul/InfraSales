import { useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { type ReactNode, type RefObject, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { listFeedsOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { FeedRead } from "#/client/types.gen.ts";
import { EmptyState } from "#/components/empty-state.tsx";
import { ViewTabs } from "#/components/filter-bar/view-tabs.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs.tsx";
import { AddFeed } from "./add-feed.tsx";
import {
  type FeedFilters,
  type FeedSearch,
  feedFiltersOf,
  inView,
  narrowed,
  shownFeeds,
  VIEWS,
} from "./feed-filters.ts";
import { FeedOverlap } from "./feed-overlap.tsx";
import { FeedTable } from "./feed-table.tsx";
import { FeedToolbar } from "./feed-toolbar.tsx";

const FROM = "/_signed-in/feeds";
const FRESH_MS = 60_000;

// What an empty list says: nothing matches the search and filters, or the view holds no Feed.
function NothingShown({ filters }: { filters: FeedFilters }) {
  const { t } = useTranslation();
  const { view } = filters;
  const [title, description] =
    narrowed(filters) || view === "all"
      ? [t("feeds.noMatch.title"), t("feeds.noMatch.description")]
      : [t(`feeds.viewEmpty.${view}.title`), t(`feeds.viewEmpty.${view}.description`)];
  return (
    <EmptyState
      title={title}
      description={description}
      className="rounded-lg border border-dashed"
    />
  );
}

interface ListedProps {
  feeds: FeedRead[]; // every Feed, at least one
  add: ReactNode; // "Add Feed" and its status, at the end of the tabs' row
  focusAfter: RefObject<HTMLElement | null>; // once a Feed is deleted
  onDeleted: (feed: FeedRead) => void;
}

// The Feeds as views with counts (all, those that need attention, the disabled ones) beside
// "Add Feed", then a search, filters, an order and a grouping over the chosen view's list. All of
// it lives in the URL, and filters in place: the API returns every Feed at once.
function ListedFeeds({ feeds, add, focusAfter, onDeleted }: ListedProps) {
  const { t, i18n } = useTranslation();
  const search = useSearch({ from: FROM });
  const navigate = useNavigate({ from: "/feeds" });
  const change = (patch: Partial<FeedSearch>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true });
  const filters = feedFiltersOf(search);
  const now = new Date();
  const { inView: viewed, shown } = shownFeeds(feeds, filters, now, i18n.language);
  const count =
    shown.length === viewed.length
      ? t("feeds.count", { count: viewed.length })
      : t("feeds.filtered", { shown: shown.length, count: viewed.length });
  const views = VIEWS.map((view) => ({
    value: view,
    label: t(`feeds.views.${view}`),
    count: feeds.filter((feed) => inView(feed, view)).length,
  }));

  return (
    <ViewTabs
      views={views}
      value={filters.view}
      label={t("feeds.views.label")}
      actions={add}
      onChange={(view) => change({ view: view === "all" ? undefined : view })}
    >
      <FeedToolbar filters={filters} viewed={viewed} now={now} count={count} onChange={change} />
      {shown.length === 0 ? (
        <NothingShown filters={filters} />
      ) : (
        <FeedTable
          shown={shown}
          group={filters.group}
          count={count}
          now={now}
          focusAfter={focusAfter}
          onDeleted={onDeleted}
        />
      )}
    </ViewTabs>
  );
}

// Every Feed InfraSales collects from (admins), as the route's loader read them: loading and
// failing are the router's to show. A status beside "Add Feed" says which Feed was added or
// deleted last; the button sits beside the views, or alone over the empty state. A second tab
// shows which Feeds list the same documents; it is read only once opened.
export function Feeds() {
  const { t } = useTranslation();
  const { data: feeds } = useSuspenseQuery({
    ...listFeedsOptions(),
    staleTime: FRESH_MS, // as the loader just read it, however long the page took to show
  });
  const [said, setSaid] = useState<string | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const add = (
    <>
      <p role="status" className="text-muted-foreground text-sm empty:sr-only">
        {said}
      </p>
      <AddFeed
        ref={addButton}
        onOpen={() => setSaid(null)}
        onAdded={(feed) => setSaid(t("feeds.add.added", { name: feed.name }))}
      />
    </>
  );

  const names = new Map(feeds.map((feed) => [feed.slug, feed.name]));

  return (
    <Tabs defaultValue="list">
      <TabsList variant="line" aria-label={t("feeds.tabs.label")}>
        <TabsTrigger value="list">{t("feeds.tabs.list")}</TabsTrigger>
        <TabsTrigger value="overlap">{t("feeds.tabs.overlap")}</TabsTrigger>
      </TabsList>
      <TabsContent value="list" className="pt-2">
        {feeds.length === 0 ? (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-center justify-end gap-3">{add}</div>
            <EmptyState
              title={t("feeds.empty.title")}
              description={t("feeds.empty.description")}
              className="rounded-lg border border-dashed"
            />
          </div>
        ) : (
          <ListedFeeds
            feeds={feeds}
            add={add}
            focusAfter={addButton}
            onDeleted={(feed) => setSaid(t("feeds.delete.deleted", { name: feed.name }))}
          />
        )}
      </TabsContent>
      <TabsContent value="overlap" className="pt-2">
        <FeedOverlap names={names} />
      </TabsContent>
    </Tabs>
  );
}
