import { CSPProvider } from "@base-ui/react/csp-provider";
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ThemeProvider } from "#/components/theme-provider.tsx";
import type { AppRouter } from "./router.tsx";

// The app from `createApp`: its query cache for every screen, its router for the pages, the
// theme. Base UI renders no <style> elements, which the production CSP blocks: the one rule they
// carry is in styles.css.
export function App({ router, queryClient }: { router: AppRouter; queryClient: QueryClient }) {
  return (
    <CSPProvider disableStyleElements={true}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ThemeProvider>
    </CSPProvider>
  );
}
