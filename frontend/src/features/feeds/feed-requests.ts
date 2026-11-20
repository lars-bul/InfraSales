import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "#/api/errors.ts";
import {
  addFeedMutation,
  deleteFeedMutation,
  listFeedsOptions,
  listFeedsQueryKey,
  suggestFeedMutation,
} from "#/client/@tanstack/react-query.gen.ts";
import type { FeedCreate, FeedRead, Suggestion } from "#/client/types.gen.ts";

const NOT_FOUND = 404; // no Feed has that ID (any more)
const CONFLICT = 409; // adding: a Feed has that address already; deleting: it has Sources
const UNPROCESSABLE = 422; // a malformed request, or (suggest) a site that offers no Feed
const GATEWAY_TIMEOUT = 504; // the site did not answer in time

// Why nothing was found or added; each has its message in the locale (`feeds.add.problems`).
type Problem = "invalid" | "timeout" | "exists" | "failed";

type Found =
  | { outcome: "found"; suggestion: Suggestion }
  // The site's own answer, as the API words it (not allowed, blocks the bot, unreadable,
  // nothing found): shown as it comes, the one text not in the locale for now.
  | { outcome: "refused"; message: string }
  | { outcome: Problem };

type Added = { outcome: "added"; feed: FeedRead } | { outcome: Problem };

interface Deleted {
  outcome: "deleted" | "hasSources" | "failed";
}

// What FastAPI answers for a refusal of its own (`HTTPException`): `detail` is a sentence. A
// validation error's `detail` is a list instead.
function refusal(body: unknown): string | undefined {
  if (typeof body === "object" && body !== null && "detail" in body) {
    return typeof body.detail === "string" ? body.detail : undefined;
  }
  return undefined;
}

function foundProblem(error: unknown): Found {
  if (!(error instanceof ApiError)) {
    return { outcome: "failed" };
  }
  if (error.status === GATEWAY_TIMEOUT) {
    return { outcome: "timeout" };
  }
  if (error.status !== UNPROCESSABLE) {
    return { outcome: "failed" };
  }
  const message = refusal(error.body);
  return message === undefined ? { outcome: "invalid" } : { outcome: "refused", message };
}

// An address without a scheme ("heizwerk-journal.test") is meant as a web address: it gets `https://`.
const SCHEME = /^[a-z][a-z\d+.-]*:\/\//iu;

function withScheme(address: string): string {
  const trimmed = address.trim();
  return SCHEME.test(trimmed) ? trimmed : `https://${trimmed}`;
}

/** Reads the Feed list again: the page shows it. */
function refreshFeeds(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: listFeedsQueryKey() });
}

/** Asks InfraSales which Feed to add for the site at an address. Nothing is stored. */
function useFindFeed(): (address: string) => Promise<Found> {
  const { mutateAsync } = useMutation(suggestFeedMutation());
  return async (address) =>
    await mutateAsync({ body: { url: withScheme(address) } }).then(
      (suggestion): Found => ({ outcome: "found", suggestion }),
      foundProblem,
    );
}

/**
 * Adds a Feed, then reads the Feed list again so it shows. Never retried: an add left without
 * answer (no connection, the deadline) may have arrived, so the list is read to find out; a
 * Feed with the address sent means it did.
 */
function useAddFeed(): (feed: FeedCreate) => Promise<Added> {
  const queryClient = useQueryClient();
  const { mutateAsync } = useMutation(addFeedMutation());

  async function unanswered(sent: FeedCreate): Promise<Added> {
    const feeds = await queryClient.fetchQuery(listFeedsOptions()).catch(() => []);
    const feed = feeds.find((each) => each.url === sent.url);
    return feed === undefined ? { outcome: "failed" } : { outcome: "added", feed };
  }

  return async (feed) => {
    const sent = { ...feed, url: withScheme(feed.url) };
    const added = await mutateAsync({ body: sent }).then(
      (stored): Added => ({ outcome: "added", feed: stored }),
      (error: unknown): Added | Promise<Added> => {
        if (!(error instanceof ApiError)) {
          return unanswered(sent);
        }
        if (error.status === CONFLICT) {
          return { outcome: "exists" };
        }
        return { outcome: error.status === UNPROCESSABLE ? "invalid" : "failed" };
      },
    );
    if (added.outcome === "added") {
      refreshFeeds(queryClient);
    }
    return added;
  };
}

/**
 * Deletes a Feed that has collected no Sources, then reads the Feed list again; one already
 * gone counts as deleted. One that collected Sources meanwhile stays: the list is left as it
 * is, so the question that says so stays open (the caller reads it again once it closes).
 * Never retried: a delete left without answer is resolved by reading the list.
 */
function useDeleteFeed(): (feed: FeedRead) => Promise<Deleted> {
  const queryClient = useQueryClient();
  const { mutateAsync } = useMutation(deleteFeedMutation());

  async function unanswered(feed: FeedRead): Promise<Deleted> {
    const feeds = await queryClient.fetchQuery(listFeedsOptions()).catch(() => undefined);
    const gone = feeds !== undefined && !feeds.some((each) => each.id === feed.id);
    return { outcome: gone ? "deleted" : "failed" };
  }

  return async (feed) => {
    const deleted = await mutateAsync({ path: { feed_id: feed.id } }).then(
      (): Deleted => ({ outcome: "deleted" }),
      (error: unknown): Deleted | Promise<Deleted> => {
        if (!(error instanceof ApiError)) {
          return unanswered(feed);
        }
        if (error.status === NOT_FOUND) {
          return { outcome: "deleted" };
        }
        return { outcome: error.status === CONFLICT ? "hasSources" : "failed" };
      },
    );
    if (deleted.outcome === "deleted") {
      refreshFeeds(queryClient);
    }
    return deleted;
  };
}

export { type Problem, refreshFeeds, useAddFeed, useDeleteFeed, useFindFeed };
