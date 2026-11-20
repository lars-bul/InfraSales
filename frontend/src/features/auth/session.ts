import type { QueryClient } from "@tanstack/react-query";
import { queryOptions } from "@tanstack/react-query";
import { readSessionOptions, readSessionQueryKey } from "#/client/@tanstack/react-query.gen.ts";
import { client } from "#/client/client.gen.ts";
import type { AppRouter } from "#/router.tsx";

const UNAUTHORIZED = 401;
const SESSION_CHECK = "/api/auth/session";

// Who is signed in: the one source of truth (nothing in browser storage). It changes only by
// signing in or out, which reloads the page, or by the session ending: never stale until then.
export function sessionQuery() {
  return queryOptions({ ...readSessionOptions(), staleTime: Number.POSITIVE_INFINITY });
}

// Every route but the session check needs a signed-in user: a 401 means the session ended (timed
// out, or signed out elsewhere). Back to signing in, saying why; the sign-in page asks afresh.
// Returns a function that stops watching.
export function watchSession(router: AppRouter, queryClient: QueryClient): () => void {
  async function ended() {
    await queryClient.invalidateQueries({ queryKey: readSessionQueryKey(), refetchType: "none" });
    await router.navigate({ to: "/sign-in", search: { ended: true } });
  }
  const interceptor = client.interceptors.response.use((response, request) => {
    if (response.status === UNAUTHORIZED && new URL(request.url).pathname !== SESSION_CHECK) {
      ended();
    }
    return response;
  });
  return () => client.interceptors.response.eject(interceptor);
}
