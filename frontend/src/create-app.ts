import type { QueryClient } from "@tanstack/react-query";
import type { RouterHistory } from "@tanstack/react-router";
import { withStatus } from "#/api/errors.ts";
import { client } from "#/client/client.gen.ts";
import { watchSession } from "#/features/auth/session.ts";
import { createQueryClient } from "#/lib/query-client.ts";
import { createAppRouter } from "./router.tsx";

interface Options {
  history?: RouterHistory; // the browser's by default
  queryClient?: QueryClient;
}

// The app's parts, connected: one query cache, the router carrying it, and the generated
// client's interceptors. `disconnect` removes the interceptors again (the client is shared).
export function createApp({ history, queryClient = createQueryClient() }: Options = {}) {
  const router = createAppRouter(queryClient, history);
  const errors = client.interceptors.error.use(withStatus);
  const unwatch = watchSession(router, queryClient);
  const disconnect = () => {
    client.interceptors.error.eject(errors);
    unwatch();
  };
  return { queryClient, router, disconnect };
}
