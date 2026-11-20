import { createFileRoute, redirect } from "@tanstack/react-router";
import { listConfigOptions, readAiSettingsOptions } from "#/client/@tanstack/react-query.gen.ts";
import { PageError } from "#/components/unavailable.tsx";
import { SettingsPage } from "#/features/settings/settings-page.tsx";

// Admins only: viewers land on the Dashboard instead. The loader reads the schedules and the AI
// settings the page edits before it shows.
export const Route = createFileRoute("/_signed-in/settings")({
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(listConfigOptions()),
      context.queryClient.ensureQueryData(readAiSettingsOptions()),
    ]),
  staticData: { title: "settings.title", description: "settings.description" },
  component: SettingsPage,
  errorComponent: PageError,
});
