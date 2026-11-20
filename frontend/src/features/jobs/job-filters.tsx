import { SearchIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { InputGroup, InputGroupAddon, InputGroupInput } from "#/components/ui/input-group.tsx";
import { Toggle } from "#/components/ui/toggle.tsx";
import { JOB_STATES, type JobFilter } from "./job-filter.ts";

interface Props {
  filter: JobFilter;
  onChange: (filter: JobFilter) => void;
}

// Above the jobs, as Databricks' job list has it: a search by name or ID, and a segmented choice
// of all jobs, those on, or those paused.
export function JobFilters({ filter, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <InputGroup className="w-full sm:w-64">
        <InputGroupAddon>
          <SearchIcon aria-hidden={true} />
        </InputGroupAddon>
        <InputGroupInput
          type="search"
          aria-label={t("jobs.filters.search")}
          placeholder={t("jobs.filters.search")}
          value={filter.text}
          onChange={(event) => onChange({ ...filter, text: event.target.value })}
        />
      </InputGroup>
      {/* biome-ignore lint/a11y/useSemanticElements: toggle buttons, not form fields (fieldset) */}
      <div
        role="group"
        aria-label={t("jobs.filters.status")}
        className="inline-flex rounded-lg border p-0.5"
      >
        {JOB_STATES.map((state) => (
          <Toggle
            key={state}
            size="sm"
            pressed={filter.state === state}
            onPressedChange={() => onChange({ ...filter, state })}
          >
            {state === "all" ? t("jobs.filters.all") : t(`jobs.${state}`)}
          </Toggle>
        ))}
      </div>
    </div>
  );
}
