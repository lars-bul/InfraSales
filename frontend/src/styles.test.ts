import { describe, expect, test } from "vitest";
import { contrast, hex, over, parseOklch, type Rgba, tokens } from "#/test/contrast.ts";
import css from "./styles.css?raw";

// WCAG 2.1 AA: 1.4.11 non-text contrast (3:1) for focus indicators and the boundaries of inputs
// and outline buttons, which axe does not check; 1.4.3 text contrast (4.5:1) for the texts whose
// tokens were adjusted. The components draw the focus ring at 50 % (`ring-ring/50`).
const NON_TEXT = 3;
const TEXT = 4.5;
const HALF = 0.5;
// Soft fills and row tints: `bg-destructive/10` (`/20` in dark mode), the same for each status.
const SOFT = { light: 0.1, dark: 0.2 };

type Theme = "light" | "dark";
const themes = { light: tokens(css, ":root"), dark: tokens(css, ".dark") };
const surfaces = ["background", "card", "popover", "sidebar", "muted"] as const;
const behindText = ["background", "card", "popover"] as const;

/** The token `name` of `theme` as the browser paints it: translucent tokens over the page. */
function paint(theme: Theme, name: string): Rgba {
  const value = themes[theme].get(name);
  if (value === undefined) {
    throw new Error(`--${name} is missing in the ${theme} theme`);
  }
  return over(parseOklch(value), parseOklch(themes[theme].get("background") ?? ""));
}

describe.each(["light", "dark"] as const)("the %s theme", (theme) => {
  const colour = (name: string) => paint(theme, name);

  test.each(surfaces)(
    "the focus ring stands out 3:1 from the %s, at full and half strength",
    (surface) => {
      const behind = colour(surface);
      const ring = parseOklch(themes[theme].get("ring") ?? "");

      expect(contrast(over(ring, behind), behind)).toBeGreaterThanOrEqual(NON_TEXT);
      expect(contrast(over(ring, behind, HALF), behind)).toBeGreaterThanOrEqual(NON_TEXT);
    },
  );

  test("the sidebar's focus ring stands out 3:1 from the sidebar", () => {
    expect(contrast(colour("sidebar-ring"), colour("sidebar"))).toBeGreaterThanOrEqual(NON_TEXT);
  });

  test.each(
    surfaces.flatMap((surface) => [
      ["input", surface],
      ["border", surface],
    ]),
  )("%s borders (inputs, outline buttons) stand out 3:1 from the %s", (border, surface) => {
    expect(contrast(colour(border), colour(surface))).toBeGreaterThanOrEqual(NON_TEXT);
  });

  test.each(behindText)("destructive text reads 4.5:1 on the %s, plain and soft", (surface) => {
    const behind = colour(surface);
    const destructive = colour("destructive");

    expect(contrast(destructive, behind)).toBeGreaterThanOrEqual(TEXT);
    expect(contrast(destructive, over(destructive, behind, SOFT[theme]))).toBeGreaterThanOrEqual(
      TEXT,
    );
  });

  test.each(surfaces)("muted text reads 4.5:1 on the %s", (surface) => {
    expect(contrast(colour("muted-foreground"), colour(surface))).toBeGreaterThanOrEqual(TEXT);
  });
});

// InfraSales petrol (#0f4c5c) is the main colour; dark mode lightens it without changing its hue.
const OKLCH_PARTS = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/u;
const lightness = (value: string) => Number(OKLCH_PARTS.exec(value)?.[1]);
const hue = (value: string) => Number(OKLCH_PARTS.exec(value)?.[3]);

describe("the main colour", () => {
  test("is InfraSales petrol, #0f4c5c, in the light theme", () => {
    expect(hex(parseOklch(themes.light.get("primary") ?? ""))).toBe("#0f4c5c");
    expect(themes.light.get("sidebar-primary")).toBe(themes.light.get("primary"));
  });

  test("is a lighter petrol of the same hue in the dark theme", () => {
    const light = themes.light.get("primary") ?? "";
    const dark = themes.dark.get("primary") ?? "";

    expect(hue(dark)).toBeCloseTo(hue(light), 0);
    expect(lightness(dark)).toBeGreaterThan(lightness(light));
    expect(themes.dark.get("sidebar-primary")).toBe(dark);
  });

  describe.each(["light", "dark"] as const)("in the %s theme", (theme) => {
    const colour = (name: string) => paint(theme, name);

    test("its foreground reads 4.5:1 on it (buttons, the sidebar's active item)", () => {
      expect(contrast(colour("primary-foreground"), colour("primary"))).toBeGreaterThanOrEqual(
        TEXT,
      );
      expect(
        contrast(colour("sidebar-primary-foreground"), colour("sidebar-primary")),
      ).toBeGreaterThanOrEqual(TEXT);
    });

    test.each([...behindText, "sidebar"])(
      "as text (links, running runs) it reads 4.5:1 on the %s",
      (surface) => {
        expect(contrast(colour("primary"), colour(surface))).toBeGreaterThanOrEqual(TEXT);
      },
    );
  });
});

// Status colours (run results, Feed states) next to destructive: as text, as a soft badge
// (`bg-success/10 text-success`), as a solid fill with its foreground, and as a row tint of the
// soft strength under the table's body and muted text.
const statuses = ["success", "warning"] as const;

describe.each(["light", "dark"] as const)("the %s theme's status colours", (theme) => {
  const colour = (name: string) => paint(theme, name);

  test.each(statuses.flatMap((status) => behindText.map((surface) => [status, surface])))(
    "%s text reads 4.5:1 on the %s, plain and on its soft badge",
    (status, surface) => {
      const behind = colour(surface);
      const text = colour(status);

      expect(contrast(text, behind)).toBeGreaterThanOrEqual(TEXT);
      expect(contrast(text, over(text, behind, SOFT[theme]))).toBeGreaterThanOrEqual(TEXT);
    },
  );

  test.each(statuses)("%s-foreground reads 4.5:1 on its solid fill", (status) => {
    expect(contrast(colour(`${status}-foreground`), colour(status))).toBeGreaterThanOrEqual(TEXT);
  });

  test.each(
    [...statuses, "destructive"].flatMap((status) =>
      ["background", "card"].map((surface) => [status, surface]),
    ),
  )("body and muted text read 4.5:1 in a row tinted %s on the %s", (status, surface) => {
    const tinted = over(colour(status), colour(surface), SOFT[theme]);

    expect(contrast(colour("foreground"), tinted)).toBeGreaterThanOrEqual(TEXT);
    expect(contrast(colour("muted-foreground"), tinted)).toBeGreaterThanOrEqual(TEXT);
  });
});

test("contrast follows WCAG 2.1: black on white is 21:1, a colour on itself 1:1", () => {
  const white = parseOklch("oklch(1 0 0)");
  const black = parseOklch("oklch(0 0 0)");

  expect(contrast(black, white)).toBeCloseTo(21);
  expect(contrast(white, black)).toBeCloseTo(21);
  expect(contrast(white, white)).toBe(1);
  expect(over(parseOklch("oklch(0 0 0 / 50%)"), white).r).toBeCloseTo(0.5);
  expect(() => parseOklch("#fff")).toThrow("not an oklch() colour");
  expect(hex(white)).toBe("#ffffff");
  expect(hex(black)).toBe("#000000");
});
