import { createFileRoute, redirect } from "@tanstack/react-router";
import { PageError } from "#/components/unavailable.tsx";
import { auditEventsQuery, filtersIn } from "#/features/audit/audit-events.ts";
import { AuditLog } from "#/features/audit/audit-log.tsx";

// Admins only (the API enforces it too): viewers land on the Dashboard instead. The loader reads
// the newest events before the page shows; until then, or if that fails, the router's pending and
// error screens show (the error screen inside the shell, which holds the page's <main>). The
// filters live in the URL (`?actor=…&action=…`), so a filtered log can be linked to.
export const Route = createFileRoute("/_signed-in/audit")({
  validateSearch: filtersIn,
  beforeLoad: ({ context }) => {
    if (context.user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  loaderDeps: ({ search: { actor, action } }) => ({ actor, action }),
  loader: ({ context, deps }) =>
    context.queryClient.ensureInfiniteQueryData(auditEventsQuery(deps)),
  staticData: { title: "audit.title", description: "audit.description" },
  component: AuditLog,
  errorComponent: PageError,
});
