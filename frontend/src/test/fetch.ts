import { vi } from "vitest";

interface Reply {
  status?: number;
  body?: unknown;
}

/**
 * Answer API calls by "METHOD /path"; anything else fails the test. Returns the calls made.
 * A function reply is called per request and may be async (to answer later).
 */
export function stubApi(
  replies: Record<string, Reply | ((request: Request) => Reply | Promise<Reply>)>,
): Request[] {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      calls.push(request);
      const reply = replies[`${request.method} ${new URL(request.url).pathname}`];
      if (!reply) {
        throw new Error(`unexpected ${request.method} ${request.url}`);
      }
      const { status = 200, body = null } =
        typeof reply === "function" ? await reply(request) : reply;
      return new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return calls;
}

/**
 * A reply that fails the first time (an error status, no connection, or no answer until the
 * request is aborted), then answers.
 */
export function unavailableOnce(
  reply: Reply,
  how: "error" | "offline" | "stalled",
): (request: Request) => Reply | Promise<Reply> {
  let failed = false;
  return (request) => {
    if (failed) {
      return reply;
    }
    failed = true;
    if (how === "stalled") {
      return stalled(request);
    }
    if (how === "offline") {
      throw new TypeError("Failed to fetch"); // as fetch does without a connection
    }
    return { status: 503 };
  };
}

/** Replies given one per request, in turn; the last one is repeated. */
export function inTurn(...replies: [Reply, ...Reply[]]): () => Reply {
  let next = 0;
  return () => {
    const reply = replies[Math.min(next, replies.length - 1)] ?? replies[0];
    next += 1;
    return reply;
  };
}

/** A reply that never comes: as with fetch, the request fails once it is aborted. */
export function stalled(request: Request): Promise<Reply> {
  return new Promise((_, reject) => {
    request.signal.addEventListener("abort", () => reject(request.signal.reason));
  });
}
