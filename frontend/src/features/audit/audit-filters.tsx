import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Label } from "#/components/ui/label.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { type AuditFilters as Filters, SYSTEM } from "./audit-events.ts";
import { ACTIONS, isAction, person } from "./sentence.ts";

interface Props {
  filters: Filters;
  people: string[]; // the subjects to offer, besides the system
  reader: string;
  onChange: (filters: Filters) => void;
}

// Two selects above the log: whose events (one person or the system) and which kind. "All" is
// the empty value, which lifts the filter.
export function AuditFilters({ filters, people, reader, onChange }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const choose = (key: keyof Filters, value: string) =>
    onChange({ ...filters, [key]: value === "" ? undefined : value });

  return (
    <div className="flex flex-wrap gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-actor`}>{t("audit.filters.person")}</Label>
        <NativeSelect
          id={`${id}-actor`}
          value={filters.actor ?? ""}
          onChange={(event) => choose("actor", event.target.value)}
          className="min-w-48"
        >
          <NativeSelectOption value="">{t("audit.filters.everyone")}</NativeSelectOption>
          {people.map((subject) => (
            <NativeSelectOption key={subject} value={subject}>
              {person(t, subject, reader)}
            </NativeSelectOption>
          ))}
          <NativeSelectOption value={SYSTEM}>{t("audit.system")}</NativeSelectOption>
        </NativeSelect>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-action`}>{t("audit.filters.type")}</Label>
        <NativeSelect
          id={`${id}-action`}
          value={filters.action ?? ""}
          onChange={(event) => choose("action", event.target.value)}
          className="min-w-48"
        >
          <NativeSelectOption value="">{t("audit.filters.everyType")}</NativeSelectOption>
          {ACTIONS.map((action) => (
            <NativeSelectOption key={action} value={action}>
              {t(`audit.types.${action}`)}
            </NativeSelectOption>
          ))}
          {/* an action from a link that the interface does not know yet, by its code */}
          {filters.action && !isAction(filters.action) ? (
            <NativeSelectOption value={filters.action}>{filters.action}</NativeSelectOption>
          ) : null}
        </NativeSelect>
      </div>
    </div>
  );
}
