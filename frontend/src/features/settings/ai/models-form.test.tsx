import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { aiSettings, aiSettingsPage, modelsForm, pick, savedModels } from "#/test/ai.ts";
import { violations } from "#/test/axe.ts";
import { inTurn } from "#/test/fetch.ts";

test("each model is picked from its service's models, found by typing part of its id", async () => {
  const { calls, container } = aiSettingsPage(aiSettings, {
    "PUT /api/ai/models": { body: { ...aiSettings.models, revision: 2 } },
  });
  const form = await modelsForm();

  await userEvent.selectOptions(form.getByLabelText("Chat model service"), "OpenRouter");
  const chat = await pick(form, "Chat model", "gpt");
  expect(chat.getAllByRole("option").map((option) => option.textContent)).toEqual([
    "openai/gpt-oss-20b",
  ]);
  expect(await violations(container)).toEqual([]);
  await userEvent.click(chat.getByRole("option", { name: "openai/gpt-oss-20b" }));
  const embedding = await pick(form, "Embedding model", "gemini");
  await userEvent.click(embedding.getByRole("option", { name: "google/gemini-embedding-001" }));
  await userEvent.click(form.getByRole("button", { name: "Save" }));

  await form.findByText("Saved.");
  expect(await savedModels(calls)).toEqual({
    revision: '"1"',
    body: {
      chat: { provider: "openrouter", model: "openai/gpt-oss-20b" },
      embedding: { provider: "openrouter", model: "google/gemini-embedding-001" },
    },
  });
});

test("a change someone made first is shown instead of overwritten", async () => {
  const theirs = {
    ...aiSettings,
    models: {
      ...aiSettings.models,
      chat: { provider: "openrouter" as const, model: "z-ai/glm-5" },
      revision: 2,
    },
  };
  aiSettingsPage(aiSettings, {
    "GET /api/ai": inTurn({ body: aiSettings }, { body: theirs }),
    "PUT /api/ai/models": { status: 412 },
  });
  const form = await modelsForm();

  await userEvent.click(form.getByRole("button", { name: "Save" }));

  expect(
    await form.findByText("Not saved: someone changed this meanwhile. Their change is shown now."),
  ).toBeTruthy();
  expect(form.getByRole("combobox", { name: "Chat model" })).toHaveProperty("value", "z-ai/glm-5");
  expect(form.getByLabelText("Chat model service")).toHaveProperty("value", "openrouter");
});
