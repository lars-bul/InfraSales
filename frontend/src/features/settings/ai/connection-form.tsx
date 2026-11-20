import { type SubmitEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConnectionRead } from "#/client/types.gen.ts";
import { Badge } from "#/components/ui/badge.tsx";
import { Button } from "#/components/ui/button.tsx";
import { Field, FieldError, FieldLabel } from "#/components/ui/field.tsx";
import { Input } from "#/components/ui/input.tsx";
import { type Outcome, useSaveKey } from "./save-ai.ts";

const BADGES = { set: "success", unset: "outline", unreadable: "warning" } as const;
const PROBLEMS = {
  invalid: "settings.ai.invalidKey",
  unstorable: "settings.ai.unstorable",
  stale: "settings.ai.stale",
  failed: "settings.ai.failed",
} as const;

function problemOf(outcome: string): (typeof PROBLEMS)[keyof typeof PROBLEMS] | undefined {
  return Object.hasOwn(PROBLEMS, outcome) ? PROBLEMS[outcome as keyof typeof PROBLEMS] : undefined;
}

interface Props {
  connection: ConnectionRead;
  storable: boolean;
}

export function ConnectionForm({ connection, storable }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const save = useSaveKey(connection);
  const [apiKey, setApiKey] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "idle" | "saving">("idle");
  const problem = problemOf(outcome);

  async function store(key: string | null) {
    setOutcome("saving");
    const saved = await save(key);
    if (saved.outcome === "saved") {
      setApiKey("");
    }
    setOutcome(saved.outcome);
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    await store(apiKey);
  }

  return (
    <form aria-labelledby={`${id}-name`} onSubmit={submit} className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id={`${id}-name`} className="font-medium">
          {t(`settings.ai.providers.${connection.provider}`)}
        </h3>
        <Badge variant={BADGES[connection.key]}>{t(`settings.ai.keys.${connection.key}`)}</Badge>
      </div>
      <fieldset disabled={!storable || outcome === "saving"} className="grid gap-3">
        <Field data-invalid={problem !== undefined}>
          <FieldLabel htmlFor={`${id}-key`}>{t("settings.ai.newKey")}</FieldLabel>
          <Input
            id={`${id}-key`}
            type="password"
            autoComplete="off"
            spellCheck={false}
            required={true}
            value={apiKey}
            aria-invalid={problem !== undefined}
            aria-describedby={problem ? `${id}-problem` : undefined}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit">{t("settings.ai.saveKey")}</Button>
          {connection.key === "unset" ? null : (
            <Button type="button" variant="outline" onClick={() => store(null)}>
              {t("settings.ai.removeKey")}
            </Button>
          )}
          <p role="status" className="text-muted-foreground text-sm">
            {outcome === "saving" || outcome === "saved" ? t(`settings.ai.${outcome}`) : null}
          </p>
        </div>
      </fieldset>
      {problem ? <FieldError id={`${id}-problem`}>{t(problem)}</FieldError> : null}
    </form>
  );
}
