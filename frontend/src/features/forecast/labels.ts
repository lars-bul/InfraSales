import type { TFunction } from "i18next";
import type { en } from "#/i18n/locales/en.ts";

type Feature = keyof typeof en.forecast.features;

const FEATURES = new Set<string>([
  "log_population",
  "log_density",
  "large_city",
  "plan_deadline_passed",
  "heat_plan_started",
  "heat_plan_adopted",
  "years_since_heat_plan",
  "recent_feasibility_study",
  "recent_council_decision",
  "recent_funding_granted",
  "recent_roadmap_published",
  "recent_heat_company_founded",
  "recent_job_posting",
  "recent_heat_source_project",
  "recent_budget_allocated",
  "gas_concession_ends_soon",
  "construction_planned",
  "recent_planning_tenders",
  "recent_construction_tenders",
  "construction_tenders_before",
  "framework_ends_soon",
  "district_heating_share",
  "gas_heating_share",
] satisfies Feature[]);

function isFeature(name: string): name is Feature {
  return FEATURES.has(name);
}

/** A feature's name for a reader; one the app does not know yet keeps its code. */
export function featureLabel(t: TFunction, name: string): string {
  return isFeature(name) ? t(`forecast.features.${name}`) : name;
}

/**
 * The Länder by the first two digits of the AGS: a region to narrow the forecast to. Their names
 * are proper names, the same in every language.
 */
export const LAENDER = [
  ["01", "Schleswig-Holstein"],
  ["02", "Hamburg"],
  ["03", "Niedersachsen"],
  ["04", "Bremen"],
  ["05", "Nordrhein-Westfalen"],
  ["06", "Hessen"],
  ["07", "Rheinland-Pfalz"],
  ["08", "Baden-Württemberg"],
  ["09", "Bayern"],
  ["10", "Saarland"],
  ["11", "Berlin"],
  ["12", "Brandenburg"],
  ["13", "Mecklenburg-Vorpommern"],
  ["14", "Sachsen"],
  ["15", "Sachsen-Anhalt"],
  ["16", "Thüringen"],
] as const;
