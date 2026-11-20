import { screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { renderTranslated } from "#/test/render.tsx";
import { Unavailable } from "./unavailable.tsx";

test("an outage is announced with a way to try again", async () => {
  const retry = vi.fn();
  const { container } = renderTranslated(<Unavailable onRetry={retry} />);

  await userEvent.click(screen.getByRole("button", { name: "Try again" }));

  expect(screen.getByRole("alert").textContent).toContain("The service is unavailable right now.");
  expect(retry).toHaveBeenCalledOnce();
  expect(await violations(container)).toEqual([]);
});
