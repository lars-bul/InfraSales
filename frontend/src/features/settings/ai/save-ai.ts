import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "#/api/errors.ts";
import {
  readAiSettingsOptions,
  readAiSettingsQueryKey,
  updateAiConnectionMutation,
  updateAiModelsMutation,
} from "#/client/@tanstack/react-query.gen.ts";
import type { AiSettingsRead, ConnectionRead, Models, ModelsRead } from "#/client/types.gen.ts";

type Outcome = "saved" | "invalid" | "stale" | "unstorable" | "failed";

interface Saved {
  outcome: Outcome;
  stored?: AiSettingsRead | undefined;
}

const OUTCOMES: Record<number, Outcome> = { 409: "unstorable", 412: "stale", 422: "invalid" };

async function rejected(queryClient: QueryClient, error: unknown): Promise<Saved> {
  const outcome = (error instanceof ApiError && OUTCOMES[error.status]) || "failed";
  if (outcome !== "stale" && outcome !== "failed") {
    return { outcome };
  }
  const stored = await queryClient.fetchQuery(readAiSettingsOptions()).catch(() => undefined);
  return { outcome, stored };
}

function useStore() {
  const queryClient = useQueryClient();
  const store = (change: (settings: AiSettingsRead) => AiSettingsRead) =>
    queryClient.setQueryData<AiSettingsRead>(readAiSettingsQueryKey(), (settings) =>
      settings ? change(settings) : settings,
    );
  return { queryClient, store };
}

function useSaveKey(connection: ConnectionRead): (apiKey: string | null) => Promise<Saved> {
  const { queryClient, store } = useStore();
  const { mutateAsync } = useMutation(updateAiConnectionMutation());
  return async (apiKey) =>
    await mutateAsync({
      path: { provider: connection.provider },
      headers: { "if-match": `"${connection.revision}"` },
      body: { api_key: apiKey },
    }).then(
      (saved): Saved => {
        store((settings) => ({
          ...settings,
          connections: settings.connections.map((each) =>
            each.provider === saved.provider ? saved : each,
          ),
        }));
        return { outcome: "saved" };
      },
      (error: unknown) => rejected(queryClient, error),
    );
}

function useSaveModels(models: ModelsRead): (chosen: Models) => Promise<Saved> {
  const { queryClient, store } = useStore();
  const { mutateAsync } = useMutation(updateAiModelsMutation());
  return async (chosen) =>
    await mutateAsync({
      headers: { "if-match": `"${models.revision}"` },
      body: chosen,
    }).then(
      (saved): Saved => {
        store((settings) => ({ ...settings, models: saved }));
        return { outcome: "saved" };
      },
      (error: unknown) => rejected(queryClient, error),
    );
}

export { type Outcome, useSaveKey, useSaveModels };
