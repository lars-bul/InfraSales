import { createFileRoute, redirect } from "@tanstack/react-router";
import { sourceFiltersIn } from "#/features/sources/source-query.ts";
import { Sources } from "#/features/sources/sources.tsx";

// Admins only (the API enforces it too): viewers land on the Dashboard instead. The Sources load in
// place, under the filters; the filters live in the URL.
export const Route = createFileRoute("/_signed-in/sources/")({
  validateSearch: sourceFiltersIn,
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  staticData: { title: "sources.title", description: "sources.description" },
  component: Sources,
});
