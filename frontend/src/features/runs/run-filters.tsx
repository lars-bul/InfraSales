import { X } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "#/components/ui/input-group.tsx";
import { Label } from "#/components/ui/label.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { JOB_NAMES, jobNameKey } from "#/features/jobs/job-names.ts";
import { type RunFilters as Filters, RUN_STATUSES, RUN_TRIGGERS } from "./run-query.ts";

interface Props {
  filters: Filters;
  onChange: (filters: Filters) => void;
}

const ANY = "";

interface TimeProps {
  id: string;
  label: string;
  clear: string;
  value: string | undefined;
  min?: string | undefined;
  onChange: (value: string) => void;
}

// A start or end: a date and time in the browser's time zone, cleared with the button beside it
// (the empty value lifts it, as clearing the input does).
function TimeField({ id, label, clear, value, min, onChange }: TimeProps) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <InputGroup className="w-fit">
        <InputGroupInput
          id={id}
          type="datetime-local"
          value={value ?? ANY}
          min={min}
          onChange={(event) => onChange(event.target.value)}
        />
        {value ? (
          <InputGroupAddon align="inline-end">
            <InputGroupButton size="icon-xs" aria-label={clear} onClick={() => onChange(ANY)}>
              <X />
            </InputGroupButton>
          </InputGroupAddon>
        ) : null}
      </InputGroup>
    </div>
  );
}

// The filters above every job's runs, as Databricks' run list has them: which job, when it was
// scheduled (from a start until an end), how the run went and what started it. The empty value
// lifts a filter.
export function RunFilters({ filters, onChange }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const choose = (key: keyof Filters, value: string) =>
    onChange({ ...filters, [key]: value === ANY ? undefined : value });

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-job`}>{t("history.filters.job")}</Label>
        <NativeSelect
          id={`${id}-job`}
          value={filters.job ?? ANY}
          onChange={(event) => choose("job", event.target.value)}
          className="min-w-44"
        >
          <NativeSelectOption value={ANY}>{t("history.filters.everyJob")}</NativeSelectOption>
          {JOB_NAMES.map((job) => (
            <NativeSelectOption key={job} value={job}>
              {t(jobNameKey(job))}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <TimeField
        id={`${id}-start`}
        label={t("history.filters.start")}
        clear={t("history.filters.clearStart")}
        value={filters.start}
        onChange={(value) => choose("start", value)}
      />
      <TimeField
        id={`${id}-end`}
        label={t("history.filters.end")}
        clear={t("history.filters.clearEnd")}
        value={filters.end}
        min={filters.start}
        onChange={(value) => choose("end", value)}
      />
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-status`}>{t("history.filters.status")}</Label>
        <NativeSelect
          id={`${id}-status`}
          value={filters.status ?? ANY}
          onChange={(event) => choose("status", event.target.value)}
          className="min-w-36"
        >
          <NativeSelectOption value={ANY}>{t("history.filters.everyStatus")}</NativeSelectOption>
          {RUN_STATUSES.map((status) => (
            <NativeSelectOption key={status} value={status}>
              {t(`history.statuses.${status}`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-trigger`}>{t("history.filters.trigger")}</Label>
        <NativeSelect
          id={`${id}-trigger`}
          value={filters.trigger ?? ANY}
          onChange={(event) => choose("trigger", event.target.value)}
          className="min-w-36"
        >
          <NativeSelectOption value={ANY}>{t("history.filters.anyone")}</NativeSelectOption>
          {RUN_TRIGGERS.map((trigger) => (
            <NativeSelectOption key={trigger} value={trigger}>
              {t(`history.filters.${trigger}`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
    </div>
  );
}
