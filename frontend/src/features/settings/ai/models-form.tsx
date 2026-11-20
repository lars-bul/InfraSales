import { type SubmitEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ChatProvider, Models, ModelsRead, Provider } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import { Field, FieldError, FieldLabel } from "#/components/ui/field.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { ModelPicker } from "./model-picker.tsx";
import { type Outcome, useSaveModels } from "./save-ai.ts";

const SERVICES: Provider[] = ["openrouter"];
const CHAT_SERVICES: ChatProvider[] = ["openrouter", "mock"];

interface Draft {
  chatProvider: ChatProvider;
  chatModel: string;
  embeddingProvider: Provider;
  embeddingModel: string;
}

function draftOf(models: Models): Draft {
  return {
    chatProvider: models.chat.provider,
    chatModel: models.chat.model ?? "",
    embeddingProvider: models.embedding.provider,
    embeddingModel: models.embedding.model,
  };
}

function modelsOf(draft: Draft): Models {
  return {
    chat: { provider: draft.chatProvider, model: draft.chatModel.trim() },
    embedding: { provider: draft.embeddingProvider, model: draft.embeddingModel.trim() },
  };
}

interface ServiceProps<T extends ChatProvider> {
  id: string;
  label: string;
  value: T;
  options: T[];
  onChange: (value: T) => void;
}

function Service<T extends ChatProvider>({ id, label, value, options, onChange }: ServiceProps<T>) {
  const { t } = useTranslation();
  const name = (option: ChatProvider) => t(`settings.ai.providers.${option}`);
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <NativeSelect
        id={id}
        value={value}
        onChange={(event) => onChange(options.find((each) => each === event.target.value) ?? value)}
      >
        {options.map((option) => (
          <NativeSelectOption key={option} value={option}>
            {name(option)}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </Field>
  );
}

interface FieldsProps {
  id: string;
  draft: Draft;
  onChange: (part: Partial<Draft>) => void;
}

function ChatFields({ id, draft, onChange }: FieldsProps) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
      <Service
        id={`${id}-chat-service`}
        label={t("settings.ai.chatService")}
        value={draft.chatProvider}
        options={CHAT_SERVICES}
        onChange={(chatProvider) => onChange({ chatProvider, chatModel: "" })}
      />
      {draft.chatProvider === "mock" ? (
        <p className="self-end text-muted-foreground text-sm">{t("settings.ai.mockModel")}</p>
      ) : (
        <ModelPicker
          key={`${draft.chatProvider}:${draft.chatModel}`}
          id={`${id}-chat`}
          label={t("settings.ai.chat")}
          hint={t("settings.ai.chatHint")}
          provider={draft.chatProvider}
          purpose="chat"
          value={draft.chatModel}
          required={true}
          onChange={(chatModel) => onChange({ chatModel })}
        />
      )}
    </div>
  );
}

function EmbeddingFields({ id, draft, onChange }: FieldsProps) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
      <Service
        id={`${id}-embedding-service`}
        label={t("settings.ai.embeddingService")}
        value={draft.embeddingProvider}
        options={SERVICES}
        onChange={(embeddingProvider) => onChange({ embeddingProvider, embeddingModel: "" })}
      />
      <ModelPicker
        key={`${draft.embeddingProvider}:${draft.embeddingModel}`}
        id={`${id}-embedding`}
        label={t("settings.ai.embedding")}
        hint={t("settings.ai.embeddingHint")}
        provider={draft.embeddingProvider}
        purpose="embedding"
        value={draft.embeddingModel}
        required={true}
        onChange={(embeddingModel) => onChange({ embeddingModel })}
      />
    </div>
  );
}

export function ModelsForm({ models, labelledBy }: { models: ModelsRead; labelledBy: string }) {
  const { t } = useTranslation();
  const id = useId();
  const save = useSaveModels(models);
  const [draft, setDraft] = useState(() => draftOf(models));
  const [outcome, setOutcome] = useState<Outcome | "idle" | "saving">("idle");
  const change = (part: Partial<Draft>) => setDraft({ ...draft, ...part });

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setOutcome("saving");
    const saved = await save(modelsOf(draft));
    if (saved.outcome === "stale" && saved.stored) {
      setDraft(draftOf(saved.stored.models));
    }
    setOutcome(saved.outcome);
  }

  return (
    <form aria-labelledby={labelledBy} onSubmit={submit} className="grid gap-5">
      <fieldset disabled={outcome === "saving"} className="grid gap-5">
        <ChatFields id={id} draft={draft} onChange={change} />
        <EmbeddingFields id={id} draft={draft} onChange={change} />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit">{t("settings.ai.save")}</Button>
          <p role="status" className="text-muted-foreground text-sm">
            {outcome === "saving" || outcome === "saved" ? t(`settings.ai.${outcome}`) : null}
          </p>
        </div>
      </fieldset>
      {outcome === "invalid" || outcome === "stale" || outcome === "failed" ? (
        <FieldError>{t(`settings.ai.${outcome}`)}</FieldError>
      ) : null}
    </form>
  );
}
