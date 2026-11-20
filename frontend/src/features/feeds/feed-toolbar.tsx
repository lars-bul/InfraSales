import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import type { FeedKind, FeedRead } from "#/client/types.gen.ts";
import { FilterBar } from "#/components/filter-bar/filter-bar.tsx";
import type { FilterField, FilterOption } from "#/components/filter-bar/filter-values.ts";
import { Label } from "#/components/ui/label.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import type { Translate } from "#/i18n/i18n.ts";
import { CATEGORIES } from "./categories.ts";
import {
  barSearchOf,
  barValuesOf,
  type FeedFilters,
  type FeedGroup,
  type FeedSearch,
  type FeedSort,
  GROUPS,
  isStale,
  neverRead,
  SORTS,
  STATES,
} from "./feed-filters.ts";
import { KINDS } from "./kinds.ts";

// Each of `values` as an option, labelled, with how many of `feeds` have it.
function counted<T extends string>(
  values: readonly T[],
  feeds: FeedRead[],
  of: (feed: FeedRead) => T,
  label: (value: T) => string,
): FilterOption[] {
  return values.map((value) => ({
    value,
    label: label(value),
    count: feeds.filter((feed) => of(feed) === value).length,
  }));
}

// The filter bar's fields, each value with how many of the view's Feeds it would leave.
function fieldsFor(viewed: FeedRead[], now: Date, t: Translate): FilterField[] {
  const kinds = Object.keys(KINDS) as FeedKind[];
  const options = {
    state: counted(
      STATES,
      viewed,
      (feed) => feed.state,
      (state) => t(`feeds.states.${state}`),
    ),
    kind: counted(
      kinds,
      viewed,
      (feed) => feed.kind,
      (kind) => t(`feeds.kinds.${KINDS[kind]}`),
    ),
    category: counted(
      CATEGORIES,
      viewed,
      (feed) => feed.category,
      (category) => t(`feeds.categories.${category}`),
    ),
  };
  const read: FilterOption[] = [
    {
      value: "stale",
      label: t("feeds.stale"),
      count: viewed.filter((feed) => isStale(feed, now)).length,
    },
    { value: "never", label: t("feeds.neverRead"), count: viewed.filter(neverRead).length },
  ];
  return [
    { id: "state", label: t("feeds.state"), type: "options", options: options.state },
    { id: "kind", label: t("feeds.kind"), type: "options", options: options.kind },
    { id: "category", label: t("feeds.category"), type: "options", options: options.category },
    {
      id: "sources",
      label: t("feeds.sources"),
      type: "boolean",
      yes: t("feeds.hasSources"),
      no: t("feeds.noSources"),
    },
    { id: "read", label: t("feeds.lastRead"), type: "options", options: read },
  ];
}

const NONE = ""; // the group select's "Nothing": not grouped

// A select with its name in view beside it: "Sort by", "Group by".
function Named({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={id} className="whitespace-nowrap font-normal text-muted-foreground">
        {label}
      </Label>
      {children(id)}
    </div>
  );
}

// The order of the list, each named with its direction: "Name (A–Z)".
function SortSelect({ sort, onSort }: { sort: FeedSort; onSort: (sort: FeedSort) => void }) {
  const { t } = useTranslation();
  return (
    <Named label={t("feeds.sort.label")}>
      {(id) => (
        <NativeSelect
          id={id}
          value={sort}
          onChange={(event) => onSort(event.target.value as FeedSort)}
        >
          {SORTS.map((each) => (
            <NativeSelectOption key={each} value={each}>
              {t(`feeds.sort.${each}`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      )}
    </Named>
  );
}

// What the list is grouped by: nothing, or the Feeds' category, state or kind.
function GroupSelect({
  group,
  onGroup,
}: {
  group: FeedGroup | undefined;
  onGroup: (group: FeedGroup | undefined) => void;
}) {
  const { t } = useTranslation();
  return (
    <Named label={t("feeds.group.label")}>
      {(id) => (
        <NativeSelect
          id={id}
          value={group ?? NONE}
          onChange={(event) =>
            onGroup(event.target.value === NONE ? undefined : (event.target.value as FeedGroup))
          }
        >
          <NativeSelectOption value={NONE}>{t("feeds.group.none")}</NativeSelectOption>
          {GROUPS.map((each) => (
            <NativeSelectOption key={each} value={each}>
              {t(`feeds.group.${each}`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      )}
    </Named>
  );
}

interface Props {
  filters: FeedFilters;
  viewed: FeedRead[]; // the view's Feeds, which the options count
  now: Date; // which Feeds are stale
  count: ReactNode; // how many the filters leave
  onChange: (search: Partial<FeedSearch>) => void; // the search parameters to change
}

/**
 * Over the Feeds: the search (name or address), the filters (state, kind, category, Sources,
 * last read), how many are left, the order and the grouping. Each change goes to the URL.
 */
export function FeedToolbar({ filters, viewed, now, count, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <FilterBar
      fields={fieldsFor(viewed, now, t)}
      value={barValuesOf(filters)}
      onChange={(values) => onChange(barSearchOf(values))}
      search={filters.q}
      onSearch={(q) => onChange({ q })}
      searchPlaceholder={t("feeds.search")}
      onClear={() => onChange({ ...barSearchOf({}), q: undefined })}
      count={count}
      sort={
        <SortSelect
          sort={filters.sort}
          onSort={(sort) => onChange({ sort: sort === "name" ? undefined : sort })}
        />
      }
      actions={<GroupSelect group={filters.group} onGroup={(group) => onChange({ group })} />}
    />
  );
}
