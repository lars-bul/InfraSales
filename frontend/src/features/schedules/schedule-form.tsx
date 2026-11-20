import { type SubmitEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import { FieldError } from "#/components/ui/field.tsx";
import { draftOf } from "./draft.ts";
import { type Outcome, useSaveSchedule } from "./save-schedule.ts";
import { ScheduleFields } from "./schedule-fields.tsx";

interface Props {
  entry: ConfigEntryRead;
  labelledBy?: string; // the id of a heading already naming it, as on the Settings page
}

// The form edits a draft of the schedule and saves it as a whole, with the job's On/Off as the
// card's switch left it. While it saves, the form is locked: no second save, and no edit the
// outcome would not describe. A save left without answer is resolved by rereading the schedule
// before the form unlocks. Someone else's change, once read, replaces the draft.
export function ScheduleForm({ entry, labelledBy }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const saveButton = useRef<HTMLButtonElement>(null);
  const save = useSaveSchedule(entry);
  const [outcome, setOutcome] = useState<Outcome | "idle" | "saving">("idle");
  const [draft, setDraft] = useState(() => draftOf(entry.value));
  useEffect(() => {
    if (outcome !== "idle" && outcome !== "saving") {
      saveButton.current?.focus(); // unlocked again: keyboard users are back where they were
    }
  }, [outcome]);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setOutcome("saving");
    const saved = await save({ ...draft.schedule, enabled: entry.value.enabled ?? true });
    if (saved.outcome === "stale" && saved.stored) {
      setDraft(draftOf(saved.stored.value));
    }
    setOutcome(saved.outcome);
  }

  return (
    // A plain form, kept to a readable width. In a job page's Settings tab it is named by a
    // heading only screen readers need (the page's title says it already); on the Settings page,
    // by its section's heading.
    <form
      aria-labelledby={labelledBy ?? `${id}-title`}
      onSubmit={submit}
      className="grid max-w-2xl gap-4"
    >
      {labelledBy ? null : (
        <h2 id={`${id}-title`} className="sr-only">
          {t(`schedules.${entry.key}`)}
        </h2>
      )}
      <fieldset disabled={outcome === "saving"} className="grid gap-5">
        <ScheduleFields id={id} draft={draft} onChange={setDraft} />
        <div className="flex flex-wrap items-center gap-3">
          <Button ref={saveButton} type="submit">
            {t("schedules.save")}
          </Button>
          <p role="status" className="text-muted-foreground text-sm">
            {outcome === "saving" || outcome === "saved" ? t(`schedules.${outcome}`) : null}
          </p>
        </div>
      </fieldset>
      {outcome === "invalid" || outcome === "stale" || outcome === "failed" ? (
        <FieldError>{t(`schedules.${outcome}`)}</FieldError>
      ) : null}
    </form>
  );
}
