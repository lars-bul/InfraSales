import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "#/api/errors.ts";

const MAX_RETRIES = 2;
const SERVER_ERROR = 500;

// Worth trying again: a server error, no connection, or no answer before the deadline.
// A client error (4xx) would only fail the same way again.
function transient(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status >= SERVER_ERROR;
  }
  return (
    error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")
  );
}

// The app's one cache of server data. Writes are never retried behind the user's back: the
// user decides whether to try again, so nothing happens twice.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: (failures, error) => failures < MAX_RETRIES && transient(error) },
      mutations: { retry: false },
    },
  });
}
