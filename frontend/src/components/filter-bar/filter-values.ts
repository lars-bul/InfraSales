interface Field {
  id: string; // its search parameter, too
  label: string;
}

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const WEEK_DAYS = 7;
const MONTH_DAYS = 30;
const PRESET_MS: Record<PeriodPreset, number> = {
  "24h": DAY_MS,
  "7d": WEEK_DAYS * DAY_MS,
  "30d": MONTH_DAYS * DAY_MS,
};
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const RANGE = "..";
const LIST = ",";
const YES = "yes";
const NO = "no";

// A filter's value as one search parameter: "rss,sitemap", "yes", "7d" or "2026-10-01..2026-10-20".
function encode(value: FilterValue | undefined): string | undefined {
  if (!isActive(value) || value === undefined) {
    return undefined;
  }
  if (Array.isArray(value)) {
    return value.join(LIST);
  }
  if (typeof value === "boolean") {
    return value ? YES : NO;
  }
  return value.preset ?? `${value.from ?? ""}${RANGE}${value.to ?? ""}`;
}

// A search parameter as text: the router turns "true" and "3" into a boolean and a number.
function textOf(raw: unknown): string | undefined {
  if (typeof raw === "string") {
    return raw.trim() || undefined;
  }
  return typeof raw === "number" || typeof raw === "boolean" ? String(raw) : undefined;
}

// "rss,sitemap" (or the router's list) as the values; none: an empty list.
function decodeOptions(raw: unknown): string[] {
  const parts = Array.isArray(raw) ? raw.map(textOf) : textOf(raw)?.split(LIST);
  const values = (parts ?? []).map((part) => part?.trim()).filter((part) => part !== undefined);
  return values.filter((part) => part !== "");
}

// "yes" or "no" (the router may have read "true" or "false" as a boolean).
function decodeBoolean(raw: unknown): boolean | undefined {
  const text = textOf(raw)?.toLowerCase();
  if (text === YES || text === "true") {
    return true;
  }
  return text === NO || text === "false" ? false : undefined;
}

// A preset ("7d"), or a range of days ("2026-10-01..2026-10-20", either end open) when the field
// offers one.
function decodePeriod(raw: unknown, custom: boolean): Period | undefined {
  const text = textOf(raw);
  const preset = PERIOD_PRESETS.find((each) => each === text);
  if (preset) {
    return { preset };
  }
  if (!(custom && text?.includes(RANGE))) {
    return undefined;
  }
  const [from, to] = text.split(RANGE).map((day) => (DAY.test(day) ? day : undefined));
  return from || to ? { from, to } : undefined;
}

/** One value an options filter offers: what it stands for, how it reads, how many it would match. */
export interface FilterOption {
  value: string; // never a comma: the URL lists values with commas
  label: string;
  count?: number | undefined;
  group?: string | undefined; // options with the same group show under it, in the order given
}

/** A filter on any of several values ("Kind: RSS, Sitemap"), searchable when there are many. */
export interface OptionsField extends Field {
  type: "options";
  options: FilterOption[];
  searchable?: boolean | undefined;
}

/** A yes-or-no filter ("Partial: Yes"); `yes` and `no` may name the two ("Has Sources"). */
export interface BooleanField extends Field {
  type: "boolean";
  yes?: string | undefined;
  no?: string | undefined;
}

/** A filter on when something happened: the last day, week or month, or dates of one's own. */
export interface PeriodField extends Field {
  type: "period";
  custom?: boolean | undefined; // offer "Custom range" with a first and a last day
}

export type FilterField = OptionsField | BooleanField | PeriodField;

export const PERIOD_PRESETS = ["24h", "7d", "30d"] as const;
export type PeriodPreset = (typeof PERIOD_PRESETS)[number];

/** The locale key naming each preset: "24h" reads "Last 24 hours". */
export const PRESET_KEYS = {
  "24h": "filters.periods.last24h",
  "7d": "filters.periods.last7d",
  "30d": "filters.periods.last30d",
} as const satisfies Record<PeriodPreset, string>;

/** A period: one of the presets, or the days from `from` to `to` (YYYY-MM-DD, either open). */
export interface Period {
  preset?: PeriodPreset | undefined;
  from?: string | undefined;
  to?: string | undefined;
}

export type FilterValue = string[] | boolean | Period;

/** The filters set, by field id: an options field's values, a boolean, or a period. */
export type FilterValues = Partial<Record<string, FilterValue>>;

/** The values an options filter has set; none: an empty list. */
export function optionsOf(values: FilterValues, id: string): string[] {
  const value = values[id];
  return Array.isArray(value) ? value : [];
}

/** Whether a boolean filter is set to yes or no; unset: undefined. */
export function booleanOf(values: FilterValues, id: string): boolean | undefined {
  const value = values[id];
  return typeof value === "boolean" ? value : undefined;
}

/** The period a period filter is set to; unset: undefined. */
export function periodOf(values: FilterValues, id: string): Period | undefined {
  const value = values[id];
  return value !== undefined && typeof value === "object" && !Array.isArray(value)
    ? value
    : undefined;
}

/** Whether `value` narrows anything: some option, yes or no, or a period with an end. */
export function isActive(value: FilterValue | undefined): boolean {
  if (value === undefined) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "boolean") {
    return true;
  }
  return Boolean(value.preset || value.from || value.to);
}

/** The fields in `fields` that `values` sets, in their order. */
export function activeFields(fields: FilterField[], values: FilterValues): FilterField[] {
  return fields.filter((field) => isActive(values[field.id]));
}

/** `values` with `id` set to `value`, or without it when `value` narrows nothing. */
export function withValue(
  values: FilterValues,
  id: string,
  value: FilterValue | undefined,
): FilterValues {
  const { [id]: _dropped, ...rest } = values;
  return isActive(value) ? { ...rest, [id]: value } : rest;
}

/** The first `max` of `labels` and how many more there are: a chip shows "A, B +2". */
export function summarise(labels: string[], max = 2): { shown: string[]; more: number } {
  return { shown: labels.slice(0, max), more: Math.max(0, labels.length - max) };
}

/** The labels of `chosen`, in the order the field offers them; a value it does not offer as is. */
export function labelsOf(field: OptionsField, chosen: string[]): string[] {
  const offered = field.options.filter((option) => chosen.includes(option.value));
  const unknown = chosen.filter((value) => !field.options.some((option) => option.value === value));
  return [...offered.map((option) => option.label), ...unknown];
}

/** `options` grouped by their `group`, groups in the order they first appear. */
export function groupsOf(options: FilterOption[]): { group?: string; options: FilterOption[] }[] {
  const groups: { group?: string; options: FilterOption[] }[] = [];
  for (const option of options) {
    const found = groups.find((each) => each.group === option.group);
    if (found) {
      found.options.push(option);
    } else {
      groups.push({
        ...(option.group !== undefined && { group: option.group }),
        options: [option],
      });
    }
  }
  return groups;
}

/** The options whose label contains `query` (any case); no query: all of them. */
export function matching(options: FilterOption[], query: string, locale?: string): FilterOption[] {
  const typed = query.trim().toLocaleLowerCase(locale);
  return typed
    ? options.filter((option) => option.label.toLocaleLowerCase(locale).includes(typed))
    : options;
}

/** Midnight starting a YYYY-MM-DD day, in the browser's time zone. */
export function localDay(day: string): Date {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  return new Date(year, month - 1, date);
}

/**
 * When a period starts and ends, as instants to compare or send: a preset runs from that long
 * before `now` (no end); a custom range from midnight of its first day until midnight after its
 * last (`to` is exclusive). Either end may be missing.
 */
export function periodBounds(period: Period, now: Date = new Date()): { from?: Date; to?: Date } {
  if (period.preset) {
    return { from: new Date(now.getTime() - PRESET_MS[period.preset]) };
  }
  const to = period.to ? localDay(period.to) : undefined;
  to?.setDate(to.getDate() + 1);
  return { ...(period.from && { from: localDay(period.from) }), ...(to && { to }) };
}

/**
 * The filters as search parameters, one per field (undefined when it is not set, so spreading
 * this into a router's `search` lifts the filters removed).
 */
export function filtersToSearch(
  fields: FilterField[],
  values: FilterValues,
): Record<string, string | undefined> {
  return Object.fromEntries(fields.map((field) => [field.id, encode(values[field.id])]));
}

/** The filters in a URL's search parameters, by `fields`; a parameter that does not parse is ignored. */
export function filtersFromSearch(
  fields: FilterField[],
  search: Record<string, unknown>,
): FilterValues {
  let values: FilterValues = {};
  for (const field of fields) {
    const raw = search[field.id];
    let value: FilterValue | undefined;
    if (field.type === "options") {
      value = decodeOptions(raw);
    } else if (field.type === "boolean") {
      value = decodeBoolean(raw);
    } else {
      value = decodePeriod(raw, field.custom === true);
    }
    values = withValue(values, field.id, value);
  }
  return values;
}
