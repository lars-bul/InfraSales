import type { CreateClientConfig } from "#/client/client.gen.ts";
import { withDeadline } from "./deadline.ts";

// The generated client's settings, applied when it is created.
// Same origin: the session cookie is sent, and Fetch Metadata marks requests as same-site.
// `fetch` is looked up per call, so tests can replace it.
export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: globalThis.location.origin,
  fetch: (input, init) => globalThis.fetch(withDeadline(new Request(input, init))),
});
