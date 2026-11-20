import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderTranslated } from "#/test/render.tsx";
import { Panel } from "./panel.tsx";

const CHART = "The chart";

test("a panel is a region named by its title, with its description and what it holds", () => {
  renderTranslated(
    <Panel title="Events by day" description="Found each day.">
      <p>{CHART}</p>
    </Panel>,
  );

  const region = screen.getByRole("region", { name: "Events by day" });
  expect(region.textContent).toContain("Found each day.");
  expect(region.textContent).toContain("The chart");
});
