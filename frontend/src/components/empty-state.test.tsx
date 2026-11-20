import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { EmptyState } from "./empty-state.tsx";

test("an empty list shows a title and one line saying what will appear there", async () => {
  const { container } = render(
    <EmptyState title="Nothing here yet" description="Things appear here once there are some." />,
  );

  expect(screen.getByText("Nothing here yet")).toBeTruthy();
  expect(screen.getByText("Things appear here once there are some.")).toBeTruthy();
  expect(container.textContent).toBe("Nothing here yetThings appear here once there are some.");
  expect(await violations(container)).toEqual([]);
});
