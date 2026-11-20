import type { RankedMunicipality } from "#/client/types.gen.ts";

const QUOTED = /[",;\n\r]/;
const SCORE_DIGITS = 4;

function cell(value: string | number | null): string {
  if (value === null) {
    return "";
  }
  const text = String(value);
  return QUOTED.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * The ranking as CSV for a CRM or a spreadsheet: one row per municipality, the reasons by their
 * names, separated by `|`. Semicolons separate the cells, as German spreadsheets expect, and a
 * byte order mark makes Excel read UTF-8.
 */
export function rankingCsv(
  items: RankedMunicipality[],
  header: readonly string[],
  reason: (feature: string) => string,
): string {
  const rows = items.map((item) =>
    [
      item.rank,
      item.ags,
      item.name,
      item.population,
      item.score.toFixed(SCORE_DIGITS),
      item.reasons.map((each) => reason(each.feature)).join(" | "),
    ]
      .map(cell)
      .join(";"),
  );
  return `\ufeff${[header.map(cell).join(";"), ...rows].join("\r\n")}\r\n`;
}

/** Hands `text` to the browser as a file to save. */
export function download(text: string, name: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
