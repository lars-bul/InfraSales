import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { DataTable } from "#/components/data-table.tsx";
import { EmptyState } from "#/components/empty-state.tsx";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "#/components/ui/table.tsx";
import { RecentRuns } from "#/features/runs/recent-runs.tsx";
import { JobState, NextRunOf } from "./job-details.tsx";
import { useJobEntries } from "./job-entries.ts";
import { EVERY_JOB, type JobFilter, matches } from "./job-filter.ts";
import { JobFilters } from "./job-filters.tsx";
import { JOBS } from "./job-names.ts";
import { JobSheet } from "./job-sheet.tsx";
import { scheduleSentence } from "./schedule-sentence.ts";

interface RowProps {
  entry: ConfigEntryRead;
  name: string; // the job's display name
  canEdit: boolean;
}

// A job: its name (to its page) over what it does, when it runs and next, whether it is on, and
// for admins how its last runs went; its "…" opens it at a glance in a sheet.
function JobRow({ entry, name, canEdit }: RowProps) {
  const { t, i18n } = useTranslation();
  const job = JOBS[entry.key];
  return (
    <TableRow>
      <TableCell className="whitespace-normal">
        <Link
          to="/jobs/$job"
          params={{ job }}
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          {name}
        </Link>
        <p className="text-muted-foreground">{t(`jobs.descriptions.${entry.key}`)}</p>
      </TableCell>
      <TableCell>{scheduleSentence(entry.value, i18n)}</TableCell>
      <TableCell>
        <NextRunOf entry={entry} />
      </TableCell>
      <TableCell>
        <JobState entry={entry} />
      </TableCell>
      {canEdit ? (
        <TableCell>
          <RecentRuns job={job} name={name} />
        </TableCell>
      ) : null}
      <TableCell className="w-px text-end">
        <JobSheet entry={entry} name={name} canEdit={canEdit} />
      </TableCell>
    </TableRow>
  );
}

// A job without a schedule: it runs after another job's runs (or with Run now), so it has no
// Every job in one table, as Databricks' job list: filtered by name or ID and by whether it is
// on. Each name leads to the job's page; the count says how far the filters narrow the list.
export function Jobs({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const entries = useJobEntries();
  const [filter, setFilter] = useState<JobFilter>(EVERY_JOB);
  const named = entries.map((entry) => ({ entry, name: t(`schedules.${entry.key}`) }));
  const shown = named.filter(({ entry, name }) => matches(entry, name, filter));
  const total = entries.length;
  const listed = shown.length;
  const count =
    listed === total
      ? t("jobs.caption", { count: total })
      : t("jobs.filtered", { shown: listed, count: total });

  return (
    <div className="grid gap-4">
      <JobFilters filter={filter} onChange={setFilter} />
      {/* the table's caption shows the count; this announces it as the filters change */}
      <p role="status" className="sr-only">
        {count}
      </p>
      {listed === 0 ? (
        <EmptyState
          title={t("jobs.noMatch.title")}
          description={t("jobs.noMatch.description")}
          className="rounded-lg border border-dashed"
        />
      ) : (
        <DataTable caption={count}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("jobs.name")}</TableHead>
              <TableHead scope="col">{t("jobs.schedule")}</TableHead>
              <TableHead scope="col">{t("jobs.next")}</TableHead>
              <TableHead scope="col">{t("jobs.status")}</TableHead>
              {canEdit ? <TableHead scope="col">{t("jobs.recentRuns")}</TableHead> : null}
              <TableHead scope="col">
                <span className="sr-only">{t("jobs.more")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map(({ entry, name }) => (
              <JobRow key={entry.key} entry={entry} name={name} canEdit={canEdit} />
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
  );
}
