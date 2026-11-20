import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { listFeedsOptions, readRunOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { FeedRead } from "#/client/types.gen.ts";
import { FilterBar } from "#/components/filter-bar/filter-bar.tsx";
import {
  type FilterField,
  type FilterValues,
  filtersToSearch,
} from "#/components/filter-bar/filter-values.ts";
import { CATEGORIES } from "#/features/feeds/categories.ts";
import type { Translate } from "#/i18n/i18n.ts";
import { filterValuesOf, type SourceSearch } from "./source-query.ts";

interface Props {
  search: SourceSearch;
  /** The search parameters to change: a filter undefined is lifted. */
  onChange: (changes: Partial<Record<keyof SourceSearch, string | undefined>>) => void;
  count?: ReactNode;
  actions?: ReactNode;
}

// The Feeds as options, under their categories, each with how many Sources it has.
function feedField(feeds: FeedRead[], t: Translate): FilterField {
  const sorted = [...feeds].sort(
    (a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category),
  );
  return {
    id: "feed",
    label: t("sources.filters.feed"),
    type: "options",
    searchable: true,
    options: sorted.map((feed) => ({
      value: feed.slug,
      label: feed.name,
      count: feed.sources,
      group: t(`feeds.categories.${feed.category}`),
    })),
  };
}

// The categories as options, each with how many Sources its Feeds have.
function categoryField(feeds: FeedRead[], t: Translate): FilterField {
  return {
    id: "category",
    label: t("sources.filters.category"),
    type: "options",
    options: CATEGORIES.map((category) => ({
      value: category,
      label: t(`feeds.categories.${category}`),
      ...(feeds.length > 0 && {
        count: feeds
          .filter((feed) => feed.category === category)
          .reduce((sum, feed) => sum + feed.sources, 0),
      }),
    })),
  };
}

// The run the Sources are narrowed to, as a filter of one option: the run, by when it was due.
function useRunField(run: string | undefined): FilterField | undefined {
  const { t, i18n } = useTranslation();
  const found = useQuery({
    ...readRunOptions({ path: { job: "scrape", run_id: run ?? "" } }),
    enabled: run !== undefined,
  });
  if (run === undefined) {
    return undefined;
  }
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  let label: string = t("app.loading");
  if (found.data) {
    label = time.format(new Date(found.data.scheduled_for));
  } else if (found.isError) {
    label = t("sources.filters.runUnknown");
  }
  return {
    id: "run",
    label: t("sources.filters.run"),
    type: "options",
    options: [{ value: run, label }],
  };
}

// Above the Sources: a search of their titles and addresses (as one types); filters by Feed,
// category, last change, whether they changed and whether a paywall cut them off; and, when a
// run's details led here, the run, as a chip like the others. Each change goes to the URL.
export function SourceFilters({ search, onChange, count, actions }: Props) {
  const { t } = useTranslation();
  const feeds = useQuery(listFeedsOptions()).data ?? [];
  const run = useRunField(search.run);
  const fields: FilterField[] = [
    feedField(feeds, t),
    categoryField(feeds, t),
    { id: "period", label: t("sources.filters.period"), type: "period", custom: true },
    {
      id: "changed",
      label: t("sources.filters.changed"),
      type: "boolean",
      yes: t("sources.filters.changedYes"),
      no: t("sources.filters.changedNo"),
    },
    {
      id: "partial",
      label: t("sources.filters.partial"),
      type: "boolean",
      yes: t("sources.filters.partialYes"),
      no: t("sources.filters.partialNo"),
    },
    ...(run ? [run] : []),
  ];
  const value: FilterValues = {
    ...filterValuesOf(search),
    ...(search.run && { run: [search.run] }),
  };

  return (
    <FilterBar
      fields={fields}
      value={value}
      onChange={(next) => onChange(filtersToSearch(fields, next))}
      search={search.q}
      onSearch={(q) => onChange({ q })}
      searchPlaceholder={t("sources.filters.searchPlaceholder")}
      onClear={() => onChange({ ...filtersToSearch(fields, {}), q: undefined })}
      count={count}
      actions={actions}
    />
  );
}
