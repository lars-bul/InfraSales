import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { aiSettings, aiSettingsPage, connectionForm, storedConnection } from "#/test/ai.ts";

test("a key is saved over the revision shown, then the field is emptied", async () => {
  const { calls } = aiSettingsPage(aiSettings, {
    "PUT /api/ai/connections/openrouter": storedConnection("openrouter", "set", 3),
  });
  const openrouter = await connectionForm("OpenRouter");

  await userEvent.type(openrouter.getByLabelText("New API key"), "sk-or-v1-secret");
  await userEvent.click(openrouter.getByRole("button", { name: "Save key" }));

  expect(await openrouter.findByText("Key stored")).toBeTruthy();
  expect(openrouter.getByLabelText("New API key")).toHaveProperty("value", "");
  const put = calls.find((call) => call.method === "PUT");
  expect(put?.headers.get("if-match")).toBe('"2"');
  expect(await put?.json()).toEqual({ api_key: "sk-or-v1-secret" });
});

test("a key is removed", async () => {
  const { calls } = aiSettingsPage(aiSettings, {
    "PUT /api/ai/connections/openrouter": storedConnection("openrouter", "unset", 3),
  });
  const openrouter = await connectionForm("OpenRouter");

  await userEvent.click(openrouter.getByRole("button", { name: "Remove key" }));

  expect(await openrouter.findByText("No key")).toBeTruthy();
  const put = calls.find((call) => call.method === "PUT");
  expect(put?.headers.get("if-match")).toBe('"2"');
  expect(await put?.json()).toEqual({ api_key: null });
});

test("a key the API refuses says what a key looks like, and stays in the field", async () => {
  aiSettingsPage(aiSettings, { "PUT /api/ai/connections/openrouter": { status: 422 } });
  const openrouter = await connectionForm("OpenRouter");

  await userEvent.type(openrouter.getByLabelText("New API key"), "has a space");
  await userEvent.click(openrouter.getByRole("button", { name: "Save key" }));

  expect(
    await openrouter.findByText("Not saved: an API key is 8 to 512 characters, without spaces."),
  ).toBeTruthy();
  expect(openrouter.getByLabelText("New API key")).toHaveProperty("value", "has a space");
});
