import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { renderTranslated } from "#/test/render.tsx";
import { DataTable } from "./data-table.tsx";

const CELL = "run";

test("a wide table scrolls in its own labelled region, reachable by keyboard", async () => {
  const { container } = renderTranslated(
    <DataTable caption="Recent runs">
      <tbody>
        <tr>
          <td>{CELL}</td>
        </tr>
      </tbody>
    </DataTable>,
  );

  const region = screen.getByRole("region", { name: "Recent runs" });
  expect(region.tabIndex).toBe(0);
  expect(screen.getByRole("table", { name: "Recent runs" })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});
