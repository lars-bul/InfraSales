import { SearchIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "#/components/ui/button.tsx";
import { Input } from "#/components/ui/input.tsx";
import { InputGroup, InputGroupAddon, InputGroupInput } from "#/components/ui/input-group.tsx";
import { Label } from "#/components/ui/label.tsx";
import {
  type BooleanField,
  type FilterField,
  type FilterOption,
  type FilterValue,
  groupsOf,
  matching,
  type OptionsField,
  PERIOD_PRESETS,
  type Period,
  type PeriodField,
  PRESET_KEYS,
} from "./filter-values.ts";

interface PickerProps<F extends FilterField> {
  field: F;
  value: FilterValue | undefined;
  onChange: (value: FilterValue | undefined) => void;
  onDone: () => void; // a single choice was made: the picker may close
  focusFirst?: boolean | undefined; // on mount (it replaced what had focus)
}

// Moves focus into a picker that has just replaced the list of fields, which had it.
function useFocusFirst(focus: boolean | undefined) {
  const box = useRef<HTMLFieldSetElement>(null);
  useEffect(() => {
    if (focus) {
      box.current?.querySelector<HTMLElement>("input, button")?.focus();
    }
  }, [focus]);
  return box;
}

// One option as a checkbox, with how many it matches when that is known.
function OptionRow({
  option,
  chosen,
  onToggle,
}: {
  option: FilterOption;
  chosen: string[];
  onToggle: (value: string) => void;
}) {
  const { i18n } = useTranslation();
  return (
    <Label className="cursor-pointer rounded-md px-1.5 py-1.5 font-normal hover:bg-muted">
      <input
        type="checkbox"
        className="size-4 shrink-0 accent-primary"
        checked={chosen.includes(option.value)}
        onChange={() => onToggle(option.value)}
      />
      <span className="flex-1 truncate">{option.label}</span>{" "}
      {option.count === undefined ? null : (
        <span className="text-muted-foreground text-xs tabular-nums">
          {new Intl.NumberFormat(i18n.language).format(option.count)}
        </span>
      )}
    </Label>
  );
}

// The options as checkboxes, each with how many it matches, under their groups; a search above
// them narrows the list when the field is searchable. Every tick applies at once.
function OptionsPicker({ field, value, onChange, focusFirst }: PickerProps<OptionsField>) {
  const { t, i18n } = useTranslation();
  const box = useFocusFirst(focusFirst);
  const [query, setQuery] = useState("");
  const chosen = Array.isArray(value) ? value : [];
  const shown = matching(field.options, query, i18n.language);
  const toggle = (option: string) =>
    onChange(
      chosen.includes(option) ? chosen.filter((each) => each !== option) : [...chosen, option],
    );

  return (
    <fieldset ref={box} className="grid gap-2">
      <legend className="sr-only">{field.label}</legend>
      {field.searchable ? (
        <InputGroup>
          <InputGroupAddon>
            <SearchIcon aria-hidden={true} />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            aria-label={t("filters.searchOptions", { label: field.label })}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </InputGroup>
      ) : null}
      {shown.length === 0 ? (
        <p className="px-1.5 py-1 text-muted-foreground">
          {query.trim() ? t("filters.noMatch") : t("filters.noOptions")}
        </p>
      ) : (
        <div className="-mx-1 grid max-h-72 gap-2 overflow-y-auto px-1">
          {groupsOf(shown).map(({ group, options }) =>
            group === undefined ? (
              <div key="" className="grid">
                {options.map((option) => (
                  <OptionRow key={option.value} option={option} chosen={chosen} onToggle={toggle} />
                ))}
              </div>
            ) : (
              <fieldset key={group} className="grid">
                <legend className="px-1.5 py-1 text-muted-foreground text-xs">{group}</legend>
                {options.map((option) => (
                  <OptionRow key={option.value} option={option} chosen={chosen} onToggle={toggle} />
                ))}
              </fieldset>
            ),
          )}
        </div>
      )}
    </fieldset>
  );
}

// One choice among a few, as buttons that say which is chosen; choosing one closes the picker.
function Choices<V extends string | boolean>({
  choices,
  chosen,
  onChoose,
}: {
  choices: { value: V; label: string }[];
  chosen: V | undefined;
  onChoose: (value: V) => void;
}) {
  return (
    <div className="grid">
      {choices.map((choice) => (
        <Button
          key={String(choice.value)}
          variant="ghost"
          aria-pressed={choice.value === chosen}
          className="justify-start font-normal aria-pressed:bg-muted aria-pressed:font-medium"
          onClick={() => onChoose(choice.value)}
        >
          {choice.label}
        </Button>
      ))}
    </div>
  );
}

// Yes or no, in the field's own words when it has them ("Has Sources", "None yet").
function BooleanPicker({ field, value, onChange, onDone, focusFirst }: PickerProps<BooleanField>) {
  const { t } = useTranslation();
  const box = useFocusFirst(focusFirst);
  return (
    <fieldset ref={box}>
      <legend className="sr-only">{field.label}</legend>
      <Choices
        choices={[
          { value: true, label: field.yes ?? t("filters.yes") },
          { value: false, label: field.no ?? t("filters.no") },
        ]}
        chosen={typeof value === "boolean" ? value : undefined}
        onChoose={(choice) => {
          onChange(choice);
          onDone();
        }}
      />
    </fieldset>
  );
}

// The last day, week or month (choosing one closes the picker), and, when the field offers it, a
// first and a last day of one's own, each applied as it is entered.
function PeriodPicker({ field, value, onChange, onDone, focusFirst }: PickerProps<PeriodField>) {
  const { t } = useTranslation();
  const id = useId();
  const box = useFocusFirst(focusFirst);
  const period: Period =
    value !== undefined && typeof value === "object" && !Array.isArray(value) ? value : {};
  const custom = { from: period.from, to: period.to };
  const setDay = (end: "from" | "to", day: string) =>
    onChange({ ...custom, [end]: day || undefined });

  return (
    <fieldset ref={box} className="grid gap-2">
      <legend className="sr-only">{field.label}</legend>
      <Choices
        choices={PERIOD_PRESETS.map((preset) => ({ value: preset, label: t(PRESET_KEYS[preset]) }))}
        chosen={period.preset}
        onChoose={(preset) => {
          onChange({ preset });
          onDone();
        }}
      />
      {field.custom ? (
        <fieldset className="grid gap-2 border-t pt-2">
          {/* floated, the legend sits inside the fieldset, below its border */}
          <legend className="float-left w-full px-1.5 pb-2 text-muted-foreground text-xs">
            {t("filters.periods.custom")}
          </legend>
          <div className="grid grid-cols-2 gap-2">
            {(["from", "to"] as const).map((end) => (
              <div key={end} className="grid gap-1.5">
                <Label htmlFor={`${id}-${end}`}>{t(`filters.${end}`)}</Label>
                <Input
                  id={`${id}-${end}`}
                  type="date"
                  value={custom[end] ?? ""}
                  min={end === "to" ? custom.from : undefined}
                  max={end === "from" ? custom.to : undefined}
                  onChange={(event) => setDay(end, event.target.value)}
                />
              </div>
            ))}
          </div>
        </fieldset>
      ) : null}
    </fieldset>
  );
}

/** The picker of one field's values: options to tick, yes or no, or a period. */
export function ValuePicker(props: PickerProps<FilterField>) {
  const { field } = props;
  if (field.type === "options") {
    return <OptionsPicker {...props} field={field} />;
  }
  if (field.type === "boolean") {
    return <BooleanPicker {...props} field={field} />;
  }
  return <PeriodPicker {...props} field={field} />;
}
