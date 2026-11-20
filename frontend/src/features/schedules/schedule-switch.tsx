import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { Switch } from "#/components/ui/switch.tsx";
import { type Outcome, useSaveSchedule } from "./save-schedule.ts";

interface Parts {
  control: ReactNode; // the switch, for the card's header
  messages: ReactNode; // what it says after saving, under the schedule sentence
}

/**
 * Turns a job on or off: the stored schedule, saved at once with only `enabled` changed. It shows
 * what is stored; while saving, what was asked for. Its outcome is announced: a quiet status
 * when saved, an alert (shown too) when not.
 */
export function useScheduleSwitch(entry: ConfigEntryRead, name: string): Parts {
  const { t } = useTranslation();
  const save = useSaveSchedule(entry);
  const [pending, setPending] = useState<boolean | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const enabled = entry.value.enabled ?? true;

  async function toggle(checked: boolean) {
    setPending(checked);
    setOutcome(null);
    const saved = await save({ ...entry.value, enabled: checked });
    setOutcome(saved.outcome);
    setPending(null);
  }

  return {
    control: (
      <Switch
        aria-label={t("jobs.switch", { name })}
        checked={pending ?? enabled}
        disabled={pending !== null}
        onCheckedChange={toggle}
      />
    ),
    messages: (
      <>
        <span role="status" className="sr-only">
          {outcome === "saved"
            ? t(enabled ? "jobs.switched.on" : "jobs.switched.off", { name })
            : null}
        </span>
        {outcome === null || outcome === "saved" ? null : (
          <span role="alert" className="block text-destructive">
            {t(`schedules.${outcome}`)}
          </span>
        )}
      </>
    ),
  };
}
