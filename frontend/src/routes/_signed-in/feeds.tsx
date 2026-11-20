import { createFileRoute, redirect } from "@tanstack/react-router";
import { listFeedsOptions } from "#/client/@tanstack/react-query.gen.ts";
import { PageError } from "#/components/unavailable.tsx";
import { feedSearchIn } from "#/features/feeds/feed-filters.ts";
import { Feeds } from "#/features/feeds/feeds.tsx";

// Admins only (the API enforces it too): viewers land on the Dashboard instead. The loader reads
// every Feed before the page shows; until then, or if that fails, the router's pending and error
// screens show. The view, the search, the filters and the order live in the URL
// (`?view=attention&kind=rss,sitemap`), so the Dashboard can link to the Feeds that need attention.
export const Route = createFileRoute("/_signed-in/feeds")({
  validateSearch: feedSearchIn,
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(listFeedsOptions()),
  staticData: { title: "feeds.title", description: "feeds.description" },
  component: Feeds,
  errorComponent: PageError,
});
