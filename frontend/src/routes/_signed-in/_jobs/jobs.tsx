import { createFileRoute } from "@tanstack/react-router";
import { listConfigOptions } from "#/client/@tanstack/react-query.gen.ts";
import { PageError } from "#/components/unavailable.tsx";
import { Jobs } from "#/features/jobs/jobs.tsx";

function JobsPage() {
  const { user } = Route.useRouteContext();
  return <Jobs canEdit={user.role === "admin"} />;
}

export const Route = createFileRoute("/_signed-in/_jobs/jobs")({
  loader: ({ context }) => context.queryClient.ensureQueryData(listConfigOptions()),
  component: JobsPage,
  errorComponent: PageError,
});
