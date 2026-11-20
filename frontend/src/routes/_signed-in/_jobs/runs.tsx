import { createFileRoute, redirect } from "@tanstack/react-router";
import { JobRuns } from "#/features/runs/job-runs.tsx";
import { runFiltersIn } from "#/features/runs/run-query.ts";

// Admins only (the API enforces it too): viewers land on the jobs instead. The runs load in
// place, under the filters; the filters live in the URL.
export const Route = createFileRoute("/_signed-in/_jobs/runs")({
  validateSearch: runFiltersIn,
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  component: JobRuns,
});
