import { expect, test } from "vitest";
import { i18n } from "./i18n.ts";

test("English messages are ready before the first render", () => {
  expect(i18n.isInitialized).toBe(true);
  expect(i18n.language).toBe("en");
  expect(i18n.t("app.signedInAs", { name: "Ada <b>", role: "admin" })).toBe(
    "Signed in as Ada <b> (admin)", // not HTML-escaped here: React escapes when rendering
  );
});
