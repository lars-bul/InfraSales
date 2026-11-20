import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { renderTranslated } from "#/test/render.tsx";
import type { JobFilter } from "./job-filter.ts";
import { JobFilters } from "./job-filters.tsx";

function filters(filter: JobFilter) {
  const onChange = vi.fn<(filter: JobFilter) => void>();
  const view = renderTranslated(<JobFilters filter={filter} onChange={onChange} />);
  return { onChange, ...view };
}

test("a search box and the states as toggle buttons, the chosen one pressed", async () => {
  const { container } = filters({ text: "news", state: "on" });

  expect(screen.getByRole("searchbox", { name: "Filter by name or ID" })).toHaveProperty(
    "value",
    "news",
  );
  const states = within(screen.getByRole("group", { name: "Show jobs" }));
  expect(
    states
      .getAllByRole("button")
      .map((state) => [state.textContent, state.getAttribute("aria-pressed")]),
  ).toEqual([
    ["All", "false"],
    ["On", "true"],
    ["Paused", "false"],
  ]);
  expect(await violations(container)).toEqual([]);
});

test("typing and choosing a state each hand on the whole filter", async () => {
  const { onChange } = filters({ text: "", state: "all" });

  await userEvent.type(screen.getByRole("searchbox"), "a");
  await userEvent.click(screen.getByRole("button", { name: "Paused" }));

  expect(onChange.mock.calls).toEqual([
    [{ text: "a", state: "all" }],
    [{ text: "", state: "paused" }],
  ]);
});

test("pressing the chosen state again keeps it", async () => {
  const { onChange } = filters({ text: "", state: "on" });

  await userEvent.click(screen.getByRole("button", { name: "On" }));

  expect(onChange).toHaveBeenLastCalledWith({ text: "", state: "on" });
});
