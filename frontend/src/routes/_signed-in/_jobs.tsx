import { createFileRoute, Outlet } from "@tanstack/react-router";
import { JobsPages } from "#/features/jobs/jobs-pages.tsx";

// The Jobs page's frame: its heading, and for admins its two lists as tabs, the jobs and every
// job's runs (viewers may read the jobs only).
function JobsLayout() {
  const { user } = Route.useRouteContext();
  return (
    <div className="grid gap-6">
      {user.role === "admin" ? <JobsPages /> : null}
      <Outlet />
    </div>
  );
}

export const Route = createFileRoute("/_signed-in/_jobs")({
  staticData: { title: "jobs.title", description: "jobs.description" },
  component: JobsLayout,
});
