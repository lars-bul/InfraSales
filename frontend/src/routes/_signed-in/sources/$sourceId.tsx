import { createFileRoute, redirect } from "@tanstack/react-router";
import { SourcePage } from "#/features/sources/source-page.tsx";
import type { View } from "#/features/sources/source-query.ts";

interface Search {
  v?: number | undefined; // the version shown; none: the latest
  view?: View | undefined; // none: its text
}

function searchIn({ v, view }: Record<string, unknown>): Search {
  const number = Number(v);
  return {
    v: Number.isInteger(number) && number > 0 ? number : undefined,
    view: view === "changes" || view === "text" ? view : undefined,
  };
}

function SourceRoute() {
  const { sourceId } = Route.useParams();
  const { v, view } = Route.useSearch();
  return <SourcePage sourceId={sourceId} v={v} view={view} />;
}

// One Source's page (`/sources/<id>?v=3&view=changes`): the version and the view live in the
// URL, so a version or what changed in it can be linked to. Admins only, as the Sources. The page
// heads itself (its title, under a breadcrumb).
export const Route = createFileRoute("/_signed-in/sources/$sourceId")({
  validateSearch: searchIn,
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  staticData: { title: "sources.title", headed: true },
  component: SourceRoute,
});
