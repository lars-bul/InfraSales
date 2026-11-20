import { cn } from "cn";
import { ChevronDownIcon, XIcon } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "#/components/ui/button.tsx";
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover.tsx";
import type { Translate } from "#/i18n/i18n.ts";
import {
  activeFields,
  type FilterField,
  type FilterValue,
  type FilterValues,
  isActive,
  labelsOf,
  localDay,
  type Period,
  PRESET_KEYS,
  periodOf,
  summarise,
  withValue,
} from "./filter-values.ts";
import { SearchBox } from "./search-box.tsx";
import { ValuePicker } from "./value-pickers.tsx";

const SEARCH = ""; // no filter has this id: focus goes to the search

// A period as a chip says it: "Last 7 days", "1–20 Oct 2026", "Since 1 Oct 2026".
function periodText(period: Period, t: Translate, locale: string): string {
  if (period.preset) {
    return t(PRESET_KEYS[period.preset]);
  }
  const day = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  if (period.from && period.to) {
    return day.formatRange(localDay(period.from), localDay(period.to));
  }
  return period.from
    ? t("filters.since", { from: day.format(localDay(period.from)) })
    : t("filters.until", { to: day.format(localDay(period.to ?? "")) });
}

// What a chip says a filter is set to: "RSS, Sitemap +2", "Yes", or the period.
function valuesText(field: FilterField, value: FilterValue, t: Translate, locale: string): string {
  if (field.type === "options") {
    const { shown, more } = summarise(labelsOf(field, Array.isArray(value) ? value : []));
    const list = new Intl.ListFormat(locale, { style: "short", type: "unit" }).format(shown);
    return more ? `${list} ${t("filters.more", { count: more })}` : list;
  }
  if (field.type === "boolean") {
    return value ? (field.yes ?? t("filters.yes")) : (field.no ?? t("filters.no"));
  }
  return periodText(periodOf({ [field.id]: value }, field.id) ?? {}, t, locale);
}

// Where focus goes once a filter is lifted: back to its own button, which stays (unset now), or,
// after "Clear filters", to the search, else the first filter. It moves after the page has passed
// back the filters without it.
function useFocusLater() {
  const search = useRef<HTMLInputElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    if (target === null) {
      return;
    }
    const first = buttons.current.values().next().value;
    (buttons.current.get(target) ?? search.current ?? first)?.focus();
    setTarget(null);
  }, [target]);

  return {
    search,
    later: setTarget,
    button: (id: string) => (element: HTMLButtonElement | null) => {
      if (element) {
        buttons.current.set(id, element);
      } else {
        buttons.current.delete(id);
      }
    },
  };
}

interface FilterButtonProps {
  field: FilterField;
  value: FilterValue | undefined; // undefined: not set
  onSet: (value: FilterValue | undefined) => void;
  onRemove: () => void;
  trigger: (element: HTMLButtonElement | null) => void;
}

// One filter, always in view: unset, "Kind ▾"; set, "Kind: RSS, Sitemap" with ✕ beside it.
// Pressing it opens its values either way. It stays the same button as it is set and lifted, so
// focus can come back to it when its values close.
function FilterButton({ field, value, onSet, onRemove, trigger }: FilterButtonProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const set = value !== undefined && isActive(value);
  return (
    <div
      className={cn(
        "flex h-8 items-center rounded-lg",
        set && "border border-border bg-secondary/50 dark:border-input",
      )}
    >
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          ref={trigger}
          render={
            <Button
              variant={set ? "ghost" : "outline"}
              className={set ? "max-w-80 rounded-e-none" : "border-dashed font-normal"}
            />
          }
        >
          {set ? (
            <span className="truncate">
              {t("filters.chip", {
                label: field.label,
                values: valuesText(field, value, t, i18n.language),
              })}
            </span>
          ) : (
            <>
              {field.label}
              <ChevronDownIcon aria-hidden={true} data-icon="inline-end" />
            </>
          )}
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72">
          <PopoverHeader>
            <PopoverTitle>{field.label}</PopoverTitle>
          </PopoverHeader>
          <ValuePicker field={field} value={value} onChange={onSet} onDone={() => setOpen(false)} />
        </PopoverContent>
      </Popover>
      {set ? (
        <Button
          variant="ghost"
          size="icon-sm"
          className="rounded-s-none"
          aria-label={t("filters.remove", { label: field.label })}
          onClick={onRemove}
        >
          <XIcon aria-hidden={true} />
        </Button>
      ) : null}
    </div>
  );
}

export interface FilterBarProps {
  fields: FilterField[];
  value: FilterValues;
  onChange: (value: FilterValues) => void;
  /** The words searched for; with `onSearch`, the bar shows a search box. */
  search?: string | undefined;
  onSearch?: ((search: string | undefined) => void) | undefined;
  searchPlaceholder?: string | undefined;
  /** How many the filters leave ("28 Feeds", "3 of 28 Feeds"), announced as it changes. */
  count?: ReactNode;
  /**
   * "Clear filters" lifts the filters and the search in one change; without it the bar calls
   * `onChange({})`, then `onSearch(undefined)`.
   */
  onClear?: (() => void) | undefined;
  sort?: ReactNode;
  actions?: ReactNode;
}

/**
 * Above a list: a search, a button for each of `fields` (every filter in view, set or not), and
 * "Clear filters"; below them, how many the filters leave, then a sort and actions. The bar
 * holds no filters itself: the page keeps them (in its URL) and passes them back. Lifting a
 * filter leaves focus on its button; clearing them all, on the search.
 */
export function FilterBar({
  fields,
  value,
  onChange,
  search,
  onSearch,
  searchPlaceholder,
  count,
  onClear,
  sort,
  actions,
}: FilterBarProps) {
  const { t } = useTranslation();
  const focus = useFocusLater();
  const active = activeFields(fields, value);
  const remove = (id: string) => {
    focus.later(id);
    onChange(withValue(value, id, undefined));
  };
  const clear = () => {
    focus.later(SEARCH);
    if (onClear) {
      onClear();
    } else {
      onChange({});
      onSearch?.(undefined);
    }
  };
  const below = count !== undefined || sort !== undefined || actions !== undefined;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {onSearch ? (
          <SearchBox
            search={search}
            onSearch={onSearch}
            placeholder={searchPlaceholder}
            input={focus.search}
          />
        ) : null}
        {fields.length > 0 ? (
          <fieldset className="contents">
            <legend className="sr-only">{t("filters.fields")}</legend>
            {fields.map((field) => (
              <FilterButton
                key={field.id}
                field={field}
                value={value[field.id]}
                onSet={(next) =>
                  isActive(next) ? onChange(withValue(value, field.id, next)) : remove(field.id)
                }
                onRemove={() => remove(field.id)}
                trigger={focus.button(field.id)}
              />
            ))}
          </fieldset>
        ) : null}
        {active.length > 0 || (onSearch && search) ? (
          <Button variant="ghost" onClick={clear}>
            {t("filters.clear")}
          </Button>
        ) : null}
      </div>
      {below ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p role="status" className="text-muted-foreground text-sm tabular-nums empty:sr-only">
            {count}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {sort}
            {actions}
          </div>
        </div>
      ) : null}
    </div>
  );
}
