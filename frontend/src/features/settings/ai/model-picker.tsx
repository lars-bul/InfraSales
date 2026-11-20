import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDownIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { listAiModelsOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { Provider, Purpose } from "#/client/types.gen.ts";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "#/components/ui/combobox.tsx";
import { FieldDescription, FieldLabel } from "#/components/ui/field.tsx";
import { InputGroupAddon } from "#/components/ui/input-group.tsx";

const MODEL_ID = /^[\w.:/@~+-]{1,200}$/;
const SHOWN = 50;
const LISTED_FOR_MS = 600_000;

interface Props {
  id: string;
  label: string;
  hint: string;
  provider: Provider;
  purpose: Purpose;
  value: string;
  required: boolean;
  onChange: (model: string) => void;
}

export function ModelPicker(props: Props) {
  const { id, label, hint, provider, purpose, value, required, onChange } = props;
  const { t } = useTranslation();
  const [query, setQuery] = useState(value);
  const listing = useQuery({
    ...listAiModelsOptions({ path: { provider }, query: { purpose } }),
    staleTime: LISTED_FOR_MS,
    retry: false,
  });
  const listed = listing.data?.map((model) => model.id) ?? [];
  const typed = query.trim();
  const matched = [value, ...listed].some((model) =>
    model.toLowerCase().includes(typed.toLowerCase()),
  );
  const own = MODEL_ID.test(typed) && !matched ? [typed] : [];
  const items = [...new Set([...(value === "" ? [] : [value]), ...listed, ...own])];
  const status = listing.status === "error" ? t("settings.ai.notListed") : hint;
  const empty = listing.status === "pending" ? "settings.ai.loadingModels" : "settings.ai.noModel";
  const named = (model: string) =>
    own.includes(model) ? t("settings.ai.useTyped", { model }) : model;

  return (
    <div className="grid gap-2">
      <FieldLabel id={`${id}-label`} htmlFor={id}>
        {label}
      </FieldLabel>
      <Combobox
        items={items}
        value={value || null}
        limit={SHOWN}
        inputValue={query}
        onInputValueChange={setQuery}
        onValueChange={(model: string | null) => {
          if (model !== null) {
            onChange(model);
          }
        }}
      >
        <ComboboxInput
          id={id}
          aria-labelledby={`${id}-label`}
          aria-describedby={`${id}-status`}
          required={required}
          spellCheck={false}
          showTrigger={false}
          className="w-full"
        >
          <InputGroupAddon align="inline-end">
            <ChevronsUpDownIcon aria-hidden={true} />
          </InputGroupAddon>
        </ComboboxInput>
        <ComboboxContent>
          <ComboboxEmpty>{t(empty)}</ComboboxEmpty>
          <ComboboxList>
            {(model: string) => (
              <ComboboxItem key={model} value={model}>
                {named(model)}
              </ComboboxItem>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
      <FieldDescription id={`${id}-status`}>{status}</FieldDescription>
    </div>
  );
}
