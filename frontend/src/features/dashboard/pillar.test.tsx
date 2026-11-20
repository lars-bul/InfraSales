import { screen } from "@testing-library/react";
import { RssIcon } from "lucide-react";
import { expect, test } from "vitest";
import { renderTranslated } from "#/test/render.tsx";
import { Pillar } from "./pillar.tsx";

const BODY = "Body";

function pillar(active: boolean) {
  return (
    <ol>
      <Pillar name="Feeds" icon={RssIcon} figure={12} caption="Source Versions" active={active}>
        <p>{BODY}</p>
      </Pillar>
    </ol>
  );
}

test("a pillar names itself, says its number and what it counts, and holds its body", () => {
  renderTranslated(pillar(false));

  const item = screen.getByRole("listitem", { name: "Feeds" });
  expect(item.textContent).toContain("12");
  expect(item.textContent).toContain("Source Versions");
  expect(item.textContent).toContain("Body");
  expect(item.getAttribute("data-active")).toBe("false");
});

test("while a job fills it, it says so and the flow into it runs", () => {
  renderTranslated(pillar(true));

  const item = screen.getByRole("listitem", { name: "Feeds" });
  expect(item.getAttribute("data-active")).toBe("true");
  expect(item.querySelector(".animate-lane, [class*='animate-lane']")).not.toBeNull();
});
