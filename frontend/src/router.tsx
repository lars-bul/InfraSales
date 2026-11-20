import type { QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { Loading, RouteError } from "#/components/unavailable.tsx";
import { routeTree } from "./routeTree.gen.ts";

type Page =
  | "dashboard"
  | "opportunities"
  | "forecast"
  | "projects"
  | "jobs"
  | "sources"
  | "feeds"
  | "audit"
  | "settings";

// Type-checks every link, route and search parameter against the route tree.
declare module "@tanstack/react-router" {
  interface Register {
    router: AppRouter;
  }
  // What a page tells the app shell: the locale keys of its heading and the line below it.
  // A page that heads itself (`headed`, e.g. a job's page with the job's name) gets its title in
  // the top bar only.
  interface StaticDataRouteOption {
    title?: `${Page}.title`;
    description?: `${Page}.description`;
    headed?: true;
  }
}

export interface RouterContext {
  queryClient: QueryClient;
}

// Route loaders read through the query cache, so the router keeps no cache of its own
// (`defaultPreloadStaleTime: 0`): a preload on intent warms the queries the page needs.
export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    defaultErrorComponent: RouteError,
    defaultPendingComponent: Loading,
    ...(history && { history }),
  });
}

export type AppRouter = ReturnType<typeof createAppRouter>;
