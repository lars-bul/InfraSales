import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { AppShell } from "#/components/app-shell.tsx";
import { sessionQuery } from "#/features/auth/session.ts";
import { problemIn } from "#/features/auth/sign-in-problem.ts";

function SignedIn() {
  const { user } = Route.useRouteContext();
  return (
    <AppShell user={user}>
      <Outlet />
    </AppShell>
  );
}

// Every page behind it needs a signed-in user. The backend's built-in sign-in reports a failure
// to `/?signin=failed`: the reason goes along to the sign-in page.
export const Route = createFileRoute("/_signed-in")({
  validateSearch: problemIn,
  beforeLoad: async ({ context, search }) => {
    const { user } = await context.queryClient.fetchQuery(sessionQuery());
    if (!user) {
      throw redirect({ to: "/sign-in", search: problemIn(search) });
    }
    return { user };
  },
  component: SignedIn,
});
