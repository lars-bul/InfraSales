import { screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { renderTranslated } from "#/test/render.tsx";
import { ViewTabs } from "./view-tabs.tsx";

const VIEWS = [
  { value: "all", label: "All", count: 1171 },
  { value: "attention", label: "Needs attention", count: 3 },
  { value: "disabled", label: "Disabled" },
] as const;
const PANEL = "3 Feeds";

test("each view is a tab with its count; the chosen one shows its panel", async () => {
  const { container } = renderTranslated(
    <ViewTabs views={[...VIEWS]} value="attention" onChange={vi.fn()}>
      <p>{PANEL}</p>
    </ViewTabs>,
  );

  expect(screen.getByRole("tablist", { name: "Views" })).toBeTruthy();
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
    "All 1,171",
    "Needs attention 3",
    "Disabled",
  ]);
  const chosen = screen.getByRole("tab", { selected: true });
  expect(chosen.textContent).toBe("Needs attention 3");
  expect(screen.getByRole("tabpanel").textContent).toBe(PANEL);
  expect(await violations(container)).toEqual([]);
});

test("choosing another view asks the page to show it; the chosen one asks nothing", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderTranslated(
    <ViewTabs views={[...VIEWS]} value="all" onChange={onChange} label="Feeds by state" />,
  );

  await user.click(screen.getByRole("tab", { name: "All 1,171" }));
  await user.click(screen.getByRole("tab", { name: "Disabled" }));

  expect(onChange.mock.calls).toEqual([["disabled"]]);
  expect(screen.getByRole("tablist", { name: "Feeds by state" })).toBeTruthy();
  expect(screen.queryByRole("tabpanel")).toBeNull();
});
