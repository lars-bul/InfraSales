import { useState } from "react";
import { vi } from "vitest";
import { FilterBar } from "#/components/filter-bar/filter-bar.tsx";
import type {
  FilterField,
  FilterValue,
  FilterValues,
} from "#/components/filter-bar/filter-values.ts";
import { ValuePicker } from "#/components/filter-bar/value-pickers.tsx";

// A field of each kind, as the Feeds and Sources pages have them.
const FIELDS: FilterField[] = [
  {
    id: "kind",
    label: "Kind",
    type: "options",
    options: [
      { value: "rss", label: "RSS", count: 12 },
      { value: "sitemap", label: "Sitemap", count: 3 },
      { value: "html", label: "Web page", count: 1204 },
    ],
  },
  {
    id: "feed",
    label: "Feed",
    type: "options",
    searchable: true,
    options: [
      { value: "tiefbau-aktuell", label: "Tiefbau Aktuell", group: "Press" },
      { value: "trassenbau", label: "Trassenbau Report", group: "Press" },
      { value: "bnetza", label: "BNetzA", group: "Verwaltung" },
    ],
  },
  { id: "sources", label: "Sources", type: "boolean", yes: "Has Sources", no: "None yet" },
  { id: "changed", label: "Last change", type: "period", custom: true },
];

interface Props {
  initial?: FilterValues;
  fields?: FilterField[];
  onSearch?: (search: string | undefined) => void;
  withSearch?: boolean;
}

interface PickerProps {
  field: FilterField;
  initial?: FilterValue;
  onChange?: (value: FilterValue | undefined) => void;
  onDone?: () => void;
  focusFirst?: boolean;
}

/** The bar as a page holds it: the filters and the search in state, passed back as they change. */
export function FilterBarPage({
  initial = {},
  fields = FIELDS,
  onSearch,
  withSearch = true,
}: Props) {
  const [value, setValue] = useState<FilterValues>(initial);
  const [search, setSearch] = useState<string | undefined>();
  const shown = Object.keys(value).length;
  return (
    <>
      <FilterBar
        fields={fields}
        value={value}
        onChange={setValue}
        {...(withSearch && {
          search,
          onSearch: (next: string | undefined) => {
            setSearch(next);
            onSearch?.(next);
          },
        })}
        searchPlaceholder="Name or address"
        count={shown ? `${shown} of 28 Feeds` : "28 Feeds"}
      />
      <output aria-label="Filters">{JSON.stringify(value)}</output>
      <output aria-label="Search">{search ?? ""}</output>
    </>
  );
}

/** One field's values as the bar holds them: the value in state, passed back as it changes. */
export function ValuePickerPage({
  field,
  initial,
  onChange,
  onDone = vi.fn(),
  focusFirst,
}: PickerProps) {
  const [value, setValue] = useState<FilterValue | undefined>(initial);
  return (
    <ValuePicker
      field={field}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      onDone={onDone}
      focusFirst={focusFirst}
    />
  );
}
