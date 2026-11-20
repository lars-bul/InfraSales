import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { aiSettings, aiSettingsPage, connectionForm, modelsForm } from "#/test/ai.ts";
import { inTurn, unavailableOnce } from "#/test/fetch.ts";

test("a key refused for want of SECRETS_KEY says so", async () => {
  aiSettingsPage(aiSettings, { "PUT /api/ai/connections/openrouter": { status: 409 } });
  const openrouter = await connectionForm("OpenRouter");

  await userEvent.type(openrouter.getByLabelText("New API key"), "sk-or-v1-secret");
  await userEvent.click(openrouter.getByRole("button", { name: "Save key" }));

  expect(
    await openrouter.findByText("Set SECRETS_KEY on the server to store keys here."),
  ).toBeTruthy();
});

test("a save left without answer reads the settings again: one saved after all shows", async () => {
  const saved = {
    ...aiSettings,
    connections: aiSettings.connections.map((each) =>
      each.provider === "openrouter" ? { ...each, key: "set" as const, revision: 2 } : each,
    ),
  };
  aiSettingsPage(aiSettings, {
    "GET /api/ai": inTurn({ body: aiSettings }, { body: saved }),
    "PUT /api/ai/connections/openrouter": unavailableOnce({ status: 200 }, "offline"),
  });
  const openrouter = await connectionForm("OpenRouter");

  await userEvent.type(openrouter.getByLabelText("New API key"), "sk-or-v1-secret");
  await userEvent.click(openrouter.getByRole("button", { name: "Save key" }));

  expect(
    await openrouter.findByText("Not saved: the service is unavailable. Please try again."),
  ).toBeTruthy();
  expect(await openrouter.findByText("Key stored")).toBeTruthy();
});

test("a refused choice of models says so", async () => {
  aiSettingsPage(aiSettings, { "PUT /api/ai/models": { status: 422 } });
  const form = await modelsForm();

  await userEvent.click(form.getByRole("button", { name: "Save" }));

  expect(await form.findByText("Not saved: check the values.")).toBeTruthy();
});
