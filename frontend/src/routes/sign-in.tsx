import { createFileRoute, redirect } from "@tanstack/react-router";
import { CentredScreen } from "#/components/centred-screen.tsx";
import { sessionQuery } from "#/features/auth/session.ts";
import { SignIn } from "#/features/auth/sign-in.tsx";
import { type Problem, problemIn } from "#/features/auth/sign-in-problem.ts";

interface Search {
  signin?: Problem | undefined; // why signing in did not work
  ended?: true | undefined; // the session ended while the app was open
}

function SignInPage() {
  const { provider } = Route.useRouteContext();
  const { signin, ended } = Route.useSearch();
  return (
    <CentredScreen>
      <SignIn provider={provider} problem={signin} sessionEnded={ended} />
    </CentredScreen>
  );
}

// Full-screen: no navigation before signing in. Signed-in users have nothing to do here.
export const Route = createFileRoute("/sign-in")({
  validateSearch: ({ ended, ...search }): Search => ({
    ...problemIn(search),
    ended: ended === true ? true : undefined,
  }),
  beforeLoad: async ({ context }) => {
    const { user, provider } = await context.queryClient.fetchQuery(sessionQuery());
    if (user) {
      throw redirect({ to: "/" });
    }
    return { provider };
  },
  component: SignInPage,
});
