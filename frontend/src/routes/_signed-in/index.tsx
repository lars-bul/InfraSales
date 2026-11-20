import { createFileRoute } from "@tanstack/react-router";
import { Dashboard } from "#/features/dashboard/dashboard.tsx";

function DashboardPage() {
  const { user } = Route.useRouteContext();
  return <Dashboard user={user} />;
}

// The start page, for everyone: where InfraSales stands. It heads itself, today's date above.
export const Route = createFileRoute("/_signed-in/")({
  staticData: { title: "dashboard.title", headed: true },
  component: DashboardPage,
});
