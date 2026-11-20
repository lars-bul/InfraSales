// WCAG 2.1 contrast ratios of the stylesheet's colour tokens (`oklch(L C H)` or
// `oklch(L C H / A%)`), as the browser paints them: converted to sRGB, alpha-blended in sRGB.

const OKLCH = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+)(%?))?\s*\)$/u;

const clamp = (value: number) => Math.min(1, Math.max(0, value));

function gamma(light: number): number {
  const value = clamp(light);
  return value <= 0.003_130_8 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055;
}

function linear(channel: number): number {
  return channel <= 0.040_45 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function luminance({ r, g, b }: Rgba): number {
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** A colour in gamma-encoded sRGB, each channel 0–1, with its opacity. */
export interface Rgba {
  r: number;
  g: number;
  b: number;
  alpha: number;
}

/** Parses an `oklch()` value (CSS Color 4; OKLab to linear sRGB by Björn Ottosson's matrices). */
export function parseOklch(value: string): Rgba {
  const match = OKLCH.exec(value.trim());
  if (!match) {
    throw new Error(`not an oklch() colour: ${value}`);
  }
  const [, l = "0", c = "0", h = "0", a, percent] = match;
  const lightness = Number(l);
  const hue = (Number(h) * Math.PI) / 180;
  const okA = Number(c) * Math.cos(hue);
  const okB = Number(c) * Math.sin(hue);
  const l1 = (lightness + 0.396_337_777_4 * okA + 0.215_803_757_3 * okB) ** 3;
  const m1 = (lightness - 0.105_561_345_8 * okA - 0.063_854_172_8 * okB) ** 3;
  const s1 = (lightness - 0.089_484_177_5 * okA - 1.291_485_548 * okB) ** 3;
  let alpha = 1;
  if (a !== undefined) {
    alpha = percent ? Number(a) / 100 : Number(a);
  }
  return {
    r: gamma(4.076_741_662_1 * l1 - 3.307_711_591_3 * m1 + 0.230_969_929_2 * s1),
    g: gamma(-1.268_438_004_6 * l1 + 2.609_757_401_1 * m1 - 0.341_319_396_5 * s1),
    b: gamma(-0.004_196_086_3 * l1 - 0.703_418_614_7 * m1 + 1.707_614_701 * s1),
    alpha,
  };
}

/** An opaque colour as a CSS hex code (`#rrggbb`), each channel rounded to the nearest of 256. */
export function hex({ r, g, b }: Rgba): string {
  const byte = (channel: number) =>
    Math.round(clamp(channel) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${byte(r)}${byte(g)}${byte(b)}`;
}

/** `top` painted over the opaque `bottom`, at `opacity` times its own alpha. */
export function over(top: Rgba, bottom: Rgba, opacity = 1): Rgba {
  const alpha = top.alpha * opacity;
  const mix = (front: number, back: number) => front * alpha + back * (1 - alpha);
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), alpha: 1 };
}

/** The WCAG 2.1 contrast ratio of two opaque colours, 1–21. */
export function contrast(first: Rgba, second: Rgba): number {
  const [light, dark] = [luminance(first), luminance(second)].sort((x, y) => y - x);
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}

/** The custom properties declared in the first block of `css` that `selector` opens. */
export function tokens(css: string, selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) {
    throw new Error(`no block for ${selector}`);
  }
  const block = css.slice(start, css.indexOf("}", start));
  return new Map(
    [...block.matchAll(/--([\w-]+):\s*([^;]+);/gu)].map(([, name = "", value = ""]) => [
      name,
      value.trim(),
    ]),
  );
}
