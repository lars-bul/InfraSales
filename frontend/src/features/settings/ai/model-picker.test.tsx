import { screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { aiSettings, aiSettingsPage, modelsForm, pick, savedModels } from "#/test/ai.ts";

const SAVES = { "PUT /api/ai/models": { body: { ...aiSettings.models, revision: 2 } } };

test("of a long list only the first matches are shown, and typing narrows them", async () => {
  const many = Array.from({ length: 120 }, (_, n) => ({ id: `vendor/model-${n}`, name: `${n}` }));
  aiSettingsPage(aiSettings, {
    "GET /api/ai/connections/openrouter/models": { body: many },
  });
  const form = await modelsForm();
  await userEvent.selectOptions(form.getByLabelText("Chat model service"), "OpenRouter");

  expect((await pick(form, "Chat model", "model")).getAllByRole("option")).toHaveLength(50);
  const narrowed = await pick(form, "Chat model", "model-119");
  expect(narrowed.getAllByRole("option").map((option) => option.textContent)).toEqual([
    "vendor/model-119",
  ]);
});

test("a model the service does not list is taken as typed", async () => {
  const { calls } = aiSettingsPage(aiSettings, SAVES);
  const form = await modelsForm();

  const embedding = await pick(form, "Embedding model", "acme/embed-2026-10");
  await userEvent.click(embedding.getByRole("option", { name: "Use “acme/embed-2026-10”" }));
  await userEvent.click(form.getByRole("button", { name: "Save" }));

  await form.findByText("Saved.");
  expect((await savedModels(calls)).body.embedding).toEqual({
    provider: "openrouter",
    model: "acme/embed-2026-10",
  });
});

test("the stored model stays even if its service no longer lists it", async () => {
  const retired = { provider: "openrouter" as const, model: "qwen/qwen2-embedding" };
  aiSettingsPage({ ...aiSettings, models: { ...aiSettings.models, embedding: retired } });
  const form = await modelsForm();

  expect(form.getByRole("combobox", { name: "Embedding model" })).toHaveProperty(
    "value",
    "qwen/qwen2-embedding",
  );
});

test("a service that does not list its models says so, and a model can still be typed", async () => {
  aiSettingsPage(aiSettings, {
    "GET /api/ai/connections/openrouter/models": { status: 502 },
  });
  const form = await modelsForm();

  const chat = await pick(form, "Chat model", "qwen3.6-35b-a3b");

  expect(
    (await screen.findAllByText("The service did not list its models: type the model's id."))[0],
  ).toBeTruthy();
  expect(chat.getByRole("option", { name: "Use “qwen3.6-35b-a3b”" })).toBeTruthy();
});

test("with the mock there is no model to pick", async () => {
  aiSettingsPage({
    ...aiSettings,
    models: { ...aiSettings.models, chat: { provider: "mock", model: "" } },
  });
  const form = await modelsForm();

  expect(form.queryByRole("combobox", { name: "Chat model" })).toBeNull();
  expect(form.getByText("The mock answers without a model.")).toBeTruthy();
});
