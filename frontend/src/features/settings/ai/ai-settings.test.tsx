import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { aiSettings, aiSettingsPage, connectionForm, modelsForm } from "#/test/ai.ts";
import { violations } from "#/test/axe.ts";

test("admins see which connection has a key, never a key, and the models in use", async () => {
  const { container } = aiSettingsPage();

  const openrouter = await connectionForm("OpenRouter");
  const models = await modelsForm();

  expect(openrouter.getByText("Key stored")).toBeTruthy();
  expect(openrouter.getByLabelText("New API key")).toHaveProperty("value", "");
  expect(models.getByLabelText("Chat model")).toHaveProperty("value", "z-ai/glm-5");
  expect(await violations(container)).toEqual([]);
});

test("without SECRETS_KEY on the server no key can be entered", async () => {
  aiSettingsPage({ ...aiSettings, keys_storable: false });
  const openrouter = await connectionForm("OpenRouter");

  expect(await screen.findByText("Set SECRETS_KEY on the server to store keys here.")).toBeTruthy();
  expect(openrouter.getByLabelText("New API key").matches(":disabled")).toBe(true);
});

test("an unreadable key asks to be entered again", async () => {
  aiSettingsPage({
    ...aiSettings,
    connections: aiSettings.connections.map((each) =>
      each.provider === "openrouter" ? { ...each, key: "unreadable" } : each,
    ),
  });

  const openrouter = await connectionForm("OpenRouter");

  expect(openrouter.getByText("Key unreadable: enter it again")).toBeTruthy();
});
