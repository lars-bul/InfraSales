import { cn } from "cn";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { EveryHours, Schedule, Weekday } from "#/client/types.gen.ts";
import { Input } from "#/components/ui/input.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { scheduleSentence } from "#/features/jobs/schedule-sentence.ts";
import {
  type Draft,
  everyHours,
  type Frequency,
  WEEKDAYS,
  withDays,
  withFrequency,
  withHours,
  withOnDays,
  withTime,
} from "./draft.ts";
import { TimeZonePicker } from "./time-zone-picker.tsx";

const FREQUENCIES: readonly Frequency[] = ["hour", "day", "week"];
const MONDAY = Date.parse("2024-01-01T00:00:00Z"); // weekday names come from Intl, per language
const DAY_MS = 86_400_000;

// A pill: a frequency chip or a day. Pressed or checked, it fills with the primary colour.
const PILL =
  "inline-flex h-8 min-w-12 cursor-pointer select-none items-center justify-center rounded-full border px-3 font-medium text-xs uppercase tracking-wide transition-colors hover:bg-muted has-checked:border-primary has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50 has-disabled:cursor-not-allowed has-disabled:opacity-50 aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

interface DraftProps {
  id: string;
  draft: Draft;
  onChange: (draft: Draft) => void;
}

function useDayNames() {
  const { i18n } = useTranslation();
  return (style: "long" | "short", day: Weekday) =>
    new Intl.DateTimeFormat(i18n.language, { weekday: style, timeZone: "UTC" }).format(
      MONDAY + WEEKDAYS.indexOf(day) * DAY_MS,
    );
}

// A line of the form, as Okta lays out its flow schedule: what it sets on the left, its controls
// on the right (stacked on small screens).
function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid items-center gap-2 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-6">
      {label}
      <div className="flex flex-wrap items-center gap-2 text-sm">{children}</div>
    </div>
  );
}

function RowLabel({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <span id={id} className="font-medium text-sm">
      {children}
    </span>
  );
}

// One choice among pills, as radio buttons: the frequency, or the day of once a week.
function PillChoice<T extends string>({
  name,
  labelledBy,
  options,
  value,
  onChange,
}: {
  name: string;
  labelledBy: string;
  options: readonly { value: T; label: string; title: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className="flex flex-wrap gap-1.5">
      {options.map((option) => (
        <label key={option.value} className={PILL}>
          <input
            type="radio"
            name={name}
            value={option.value}
            aria-label={option.title}
            checked={option.value === value}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          <span aria-hidden={true}>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

// Every hour, day or week.
function FrequencyRow({ id, draft, onChange }: DraftProps) {
  const { t } = useTranslation();
  const options = FREQUENCIES.map((frequency) => {
    const label = t(`schedules.frequencies.${frequency}`);
    return { value: frequency, label, title: label };
  });
  return (
    <Row label={<RowLabel id={`${id}-frequency`}>{t("schedules.frequency")}</RowLabel>}>
      <PillChoice
        name={`${id}-frequency`}
        labelledBy={`${id}-frequency`}
        options={options}
        value={draft.frequency}
        onChange={(frequency) => onChange(withFrequency(draft, frequency))}
      />
    </Row>
  );
}

// "every [3] hours from [06:00]", "every day at [08:00]", "once a week at [08:00]".
function RunRow({ id, draft, onChange }: DraftProps) {
  const { t } = useTranslation();
  const { schedule, frequency } = draft;
  const time = (label: string) => (
    <Input
      id={`${id}-time`}
      type="time"
      aria-label={label}
      required={true}
      value={schedule.time}
      onChange={(event) => onChange(withTime(draft, event.target.value))}
      className="w-fit"
    />
  );
  return (
    <Row label={<RowLabel>{t("schedules.run")}</RowLabel>}>
      {frequency === "hour" ? (
        <>
          <span>{t("schedules.every")}</span>
          <NativeSelect
            id={`${id}-hours`}
            aria-label={t("schedules.hours")}
            value={String(draft.hours)}
            onChange={(event) =>
              onChange(withHours(draft, Number(event.target.value) as EveryHours))
            }
          >
            {everyHours.map((hours) => (
              <NativeSelectOption key={hours} value={hours}>
                {hours}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <span>{t("schedules.unit", { count: draft.hours })}</span>
          <span>{t("schedules.from")}</span>
          {time(t("schedules.startTime"))}
        </>
      ) : (
        <>
          <span>{t(frequency === "day" ? "schedules.everyDayAt" : "schedules.weeklyAt")}</span>
          {time(t("schedules.time"))}
        </>
      )}
    </Row>
  );
}

// Every few hours or once a day: "only on" ticked, the days chosen as pills; unticked, every day.
function DayPills({ draft, onChange }: Omit<DraftProps, "id">) {
  const { t } = useTranslation();
  const dayName = useDayNames();
  const { days } = draft.schedule;
  const toggle = (day: Weekday) =>
    onChange(
      withDays(
        draft,
        WEEKDAYS.filter((each) => (each === day ? !days.includes(day) : days.includes(each))),
      ),
    );
  return (
    <Row
      label={
        <label className="flex items-center gap-2 font-medium text-sm">
          <input
            type="checkbox"
            checked={draft.onDays}
            onChange={(event) => onChange(withOnDays(draft, event.target.checked))}
            className="size-4 accent-primary"
          />
          {t("schedules.onlyOn")}
        </label>
      }
    >
      <fieldset aria-label={t("schedules.days")} className="flex flex-wrap gap-1.5">
        {WEEKDAYS.map((day) => (
          <button
            key={day}
            type="button"
            aria-label={dayName("long", day)}
            aria-pressed={days.includes(day)}
            disabled={!draft.onDays}
            onClick={() => toggle(day)}
            className={cn(PILL, "bg-background")}
          >
            {dayName("short", day)}
          </button>
        ))}
      </fieldset>
    </Row>
  );
}

// Once a week: the one day it falls on.
function WeekdayChoice({ id, draft, onChange }: DraftProps) {
  const { t } = useTranslation();
  const dayName = useDayNames();
  const options = WEEKDAYS.map((day) => ({
    value: day,
    label: dayName("short", day),
    title: dayName("long", day),
  }));
  return (
    <Row label={<RowLabel id={`${id}-day`}>{t("schedules.on")}</RowLabel>}>
      <PillChoice
        name={`${id}-day`}
        labelledBy={`${id}-day`}
        options={options}
        value={draft.schedule.days[0] ?? "mon"}
        onChange={(day) => onChange(withDays(draft, [day]))}
      />
    </Row>
  );
}

// The draft as the sentence the job's details will show once it is saved.
function Summary({ schedule }: { schedule: Schedule }) {
  const { t, i18n } = useTranslation();
  return (
    <Row label={<RowLabel>{t("schedules.summary")}</RowLabel>}>
      <p role="note" aria-label={t("schedules.summary")} className="font-semibold">
        {scheduleSentence(schedule, i18n)}
      </p>
    </Row>
  );
}

// The schedule's controls, editing `draft`, laid out as Okta's flow schedule: the frequency as
// pills, how often and when as one line, the days, the time zone, and what it reads like.
export function ScheduleFields({ id, draft, onChange }: DraftProps) {
  const { schedule } = draft;
  return (
    <div className="grid gap-5">
      <FrequencyRow id={id} draft={draft} onChange={onChange} />
      <RunRow id={id} draft={draft} onChange={onChange} />
      {draft.frequency === "week" ? (
        <WeekdayChoice id={id} draft={draft} onChange={onChange} />
      ) : (
        <DayPills draft={draft} onChange={onChange} />
      )}
      <div className="grid items-center gap-2 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-6">
        <TimeZonePicker
          id={`${id}-timezone`}
          value={schedule.timezone}
          onChange={(timezone) => onChange({ ...draft, schedule: { ...schedule, timezone } })}
        />
      </div>
      <Summary schedule={schedule} />
    </div>
  );
}
