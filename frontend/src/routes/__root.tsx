import { TanStackDevtools } from "@tanstack/react-devtools";
import { ReactQueryDevtoolsPanel } from "@tanstack/react-query-devtools";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import type { RouterContext } from "#/router.tsx";

// The devtools inject <style> elements, which the production CSP blocks: they run on the Vite dev
// server alone (no CSP there). `@tanstack/devtools-vite` removes this element and its imports from
// every build; the mode check keeps them out of the tests.
function Root() {
  return (
    <>
      <Outlet />
      {import.meta.env.MODE === "development" && (
        <TanStackDevtools
          plugins={[
            { name: "TanStack Router", render: <TanStackRouterDevtoolsPanel /> },
            { name: "TanStack Query", render: <ReactQueryDevtoolsPanel /> },
          ]}
        />
      )}
    </>
  );
}

export const Route = createRootRouteWithContext<RouterContext>()({ component: Root });
