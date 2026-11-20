import { useNavigate, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { jobNameKey } from "#/features/jobs/job-names.ts";
import { RunOverview } from "#/features/jobs/run-overview.tsx";
import { RunFilters } from "./run-filters.tsx";
import { RunHistory } from "./run-history.tsx";
import type { RunFilters as Filters } from "./run-query.ts";

const FROM = "/_signed-in/_jobs/runs";

// Every job's runs in one list (admins), as Databricks' Job runs tab: the filters first (which
// job, scheduled from when until when, how it went, what started it), then the runs they pick
// at a glance, then the runs, newest first. The filters live in the URL (`?job=…&start=…`), so
// a job's page can link to its runs.
export function JobRuns() {
  const { t } = useTranslation();
  const filters = useSearch({ from: FROM });
  const navigate = useNavigate({ from: "/runs" });
  const filter = (chosen: Filters) => navigate({ search: chosen });
  const name = filters.job ? t(jobNameKey(filters.job)) : undefined;

  return (
    <div className="grid gap-6">
      <RunFilters filters={filters} onChange={filter} />
      <RunOverview filters={filters} name={name} />
      <RunHistory filters={filters} />
    </div>
  );
}
