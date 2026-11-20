import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { renderTranslated } from "#/test/render.tsx";
import { CentredScreen } from "./centred-screen.tsx";

const content = "The screen's own content";

test("a screen outside the shell names InfraSales above its content", async () => {
  const { container } = renderTranslated(
    <CentredScreen>
      <p>{content}</p>
    </CentredScreen>,
  );

  expect(screen.getByRole("main").textContent).toBe(`InfraSales${content}`);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("InfraSales");
  expect(await violations(container)).toEqual([]);
});
