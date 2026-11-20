import { ChevronsUpDownIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "#/components/ui/combobox.tsx";
import { FieldLabel } from "#/components/ui/field.tsx";
import { InputGroupAddon } from "#/components/ui/input-group.tsx";

interface Props {
  id: string;
  value: string;
  onChange: (zone: string) => void;
}

/**
 * The IANA time zones the browser knows, found by typing any part of a name ("berl" finds
 * Europe/Berlin). The stored zone is offered too, even if this browser does not list it.
 */
export function TimeZonePicker({ id, value, onChange }: Props) {
  const { t } = useTranslation();
  const zones = [...new Set([value, ...Intl.supportedValuesOf("timeZone")])];
  return (
    <>
      <FieldLabel id={`${id}-label`} htmlFor={id}>
        {t("schedules.timezone")}
      </FieldLabel>
      <Combobox
        items={zones}
        value={value}
        onValueChange={(zone: string | null) => {
          if (zone !== null) {
            onChange(zone); // clearing the text keeps the zone until another one is picked
          }
        }}
      >
        {/* Named by reference: while the list is open, the page around it (the label included)
            is hidden from assistive technology. Clicking the input opens the list, so the
            chevron is a hint, not a second (unnamed) button. */}
        <ComboboxInput
          id={id}
          aria-labelledby={`${id}-label`}
          showTrigger={false}
          className="w-full max-w-xs"
        >
          <InputGroupAddon align="inline-end">
            <ChevronsUpDownIcon aria-hidden={true} />
          </InputGroupAddon>
        </ComboboxInput>
        <ComboboxContent>
          <ComboboxEmpty>{t("schedules.noTimezone")}</ComboboxEmpty>
          <ComboboxList>
            {(zone: string) => (
              <ComboboxItem key={zone} value={zone}>
                {zone}
              </ComboboxItem>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    </>
  );
}
