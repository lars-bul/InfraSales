import { createFileRoute, redirect } from "@tanstack/react-router";
import { listConfigOptions } from "#/client/@tanstack/react-query.gen.ts";
import { PageError } from "#/components/unavailable.tsx";
import { isJob, JOBS } from "#/features/jobs/job-names.ts";
import { JobPage } from "#/features/jobs/job-page.tsx";

function JobRoute() {
  const { job } = Route.useParams();
  const { user } = Route.useRouteContext();
  return isJob(job) ? <JobPage job={job} canEdit={user.role === "admin"} /> : null;
}

// One job's page (`/jobs/scrape`). An address naming no job, or a job whose schedule is
// missing, leads to the jobs instead. The page heads itself (its job's name, under a breadcrumb).
export const Route = createFileRoute("/_signed-in/jobs/$job")({
  loader: async ({ context, params }) => {
    const entries = await context.queryClient.ensureQueryData(listConfigOptions());
    if (!entries.some((entry) => JOBS[entry.key] === params.job)) {
      throw redirect({ to: "/jobs" });
    }
  },
  staticData: { title: "jobs.title", headed: true },
  component: JobRoute,
  errorComponent: PageError,
});
