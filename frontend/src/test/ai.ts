import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { AiSettingsRead, ModelOption } from "#/client/types.gen.ts";
import { scrape } from "./entries.ts";
import { stubApi } from "./fetch.ts";
import { renderApp } from "./render.tsx";
import { noRuns } from "./runs.ts";
import { summaries } from "./summaries.ts";
import { alice, signedIn } from "./users.ts";

export const aiSettings: AiSettingsRead = {
  connections: [
    { provider: "openrouter", key: "set", revision: 2, updated_at: "2026-11-01T06:00:00Z" },
  ],
  models: {
    chat: { provider: "openrouter", model: "z-ai/glm-5" },
    embedding: { provider: "openrouter", model: "qwen/qwen3-embedding-8b" },
    revision: 1,
    updated_at: "2026-11-01T06:00:00Z",
  },
  keys_storable: true,
};

export const listedModels: Record<string, Record<string, ModelOption[]>> = {
  openrouter: {
    chat: [
      { id: "openai/gpt-oss-20b", name: "OpenAI: gpt-oss-20b" },
      { id: "z-ai/glm-5", name: "Z.ai: GLM 5" },
    ],
    embedding: [
      { id: "google/gemini-embedding-001", name: "Google: Gemini Embedding 001" },
      { id: "qwen/qwen3-embedding-8b", name: "Qwen: Qwen3 Embedding 8B" },
    ],
  },
};

/** A service's models for the purpose a request asks, as the API lists them. */
export function modelsListed(request: Request) {
  const url = new URL(request.url);
  const provider = url.pathname.split("/")[4] ?? "";
  const purpose = url.searchParams.get("purpose") ?? "";
  return { body: listedModels[provider]?.[purpose] ?? [] };
}

/** The Settings page as an admin, with `settings` stored; `replies` add or replace answers. */
export function aiSettingsPage(
  settings: AiSettingsRead = aiSettings,
  replies: Parameters<typeof stubApi>[0] = {},
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [scrape] },
    "GET /api/ai": { body: settings },
    "GET /api/ai/connections/openrouter/models": modelsListed,
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": noRuns,
    ...summaries,
    ...replies,
  });
  return { calls, ...renderApp("/settings") };
}

/** A connection's form, named by its service. */
export async function connectionForm(name: string) {
  const section = within(await screen.findByRole("region", { name: "Connections" }));
  return within(section.getByRole("form", { name }));
}

/** The models' form. */
export async function modelsForm() {
  const section = within(await screen.findByRole("region", { name: "Models" }));
  return within(section.getByRole("form", { name: "Models" }));
}

/** A connection as the API answers a save of its key. */
export function storedConnection(provider: string, key: string, revision: number) {
  return { body: { provider, key, revision, updated_at: "2026-11-11T09:00:00Z" } };
}

/** Types `typed` into the models form's `label` picker: the listbox of what matches. */
export async function pick(
  form: Awaited<ReturnType<typeof modelsForm>>,
  label: string,
  typed: string,
) {
  const picker = form.getByRole("combobox", { name: label });
  await userEvent.clear(picker);
  await userEvent.type(picker, typed);
  return within(await screen.findByRole("listbox"));
}

/** The models save among `calls`: the revision it named, and what it sent. */
export async function savedModels(calls: Request[]) {
  const put = calls.find((call) => call.method === "PUT");
  return { revision: put?.headers.get("if-match"), body: await put?.json() };
}
