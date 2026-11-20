import type {
  ModelRead,
  MunicipalityForecast,
  RankedMunicipality,
  Ranking,
} from "#/client/types.gen.ts";

// The forecast's sample answers: three municipalities in Baden-Württemberg scored by the
// heuristic on 5 January 2026, Heidelberg first for its council decision and funding.
export const heidelberg: RankedMunicipality = {
  rank: 1,
  ags: "08221000",
  name: "Heidelberg",
  population: 162_000,
  score: 0.0123,
  reasons: [
    { feature: "recent_council_decision", value: 0.69, effect: 0.97 },
    { feature: "recent_funding_granted", value: 0.69, effect: 0.95 },
  ],
};

export const ulm: RankedMunicipality = {
  rank: 2,
  ags: "08421000",
  name: "Ulm",
  population: 128_000,
  score: 0.004,
  reasons: [],
};

export const ranked: Ranking = {
  model: { version: "heuristic-1", kind: "heuristic", horizon_months: 24, calibrated: false },
  as_of: "2026-01-05",
  total: 2,
  items: [heidelberg, ulm],
};

export const learnedRanking: Ranking = {
  ...ranked,
  model: { version: "logistic-1", kind: "logistic", horizon_months: 24, calibrated: true },
  items: [{ ...heidelberg, score: 0.37 }, ulm],
};

export const noForecast: Ranking = { model: null, as_of: null, total: 0, items: [] };

export const heuristicModel: ModelRead = {
  id: "0190e1c8-0000-7000-8000-000000000001",
  version: "heuristic-1",
  kind: "heuristic",
  horizon_months: 24,
  active: true,
  trained_until: null,
  trained_at: null,
  trained_by: null,
  metrics: {},
  created_at: "2026-01-01T06:00:00Z",
};

export const learnedModel: ModelRead = {
  id: "0190e1c8-0000-7000-8000-000000000002",
  version: "logistic-2026-01-01-abc123",
  kind: "logistic",
  horizon_months: 24,
  active: false,
  trained_until: "2026-01-01",
  trained_at: "2026-01-02T06:00:00Z",
  trained_by: "cli",
  metrics: {
    cut: "2023-01-01",
    heuristic: { roc_auc: 0.71, precision_at_50: 0.2 },
    learned: { roc_auc: 0.84, precision_at_50: 0.34 },
  },
  created_at: "2026-01-02T06:00:00Z",
};

export const heidelbergFile: MunicipalityForecast = {
  ags: "08221000",
  name: "Heidelberg",
  population: 162_000,
  area_km2: 108.8,
  model: ranked.model,
  as_of: "2026-01-05",
  rank: 1,
  total: 2,
  score: 0.0123,
  reasons: heidelberg.reasons,
  features: [
    { name: "log_population", value: 11.99 },
    { name: "recent_council_decision", value: 0.69 },
  ],
  history: [
    { as_of: "2025-12-29", score: 0.011 },
    { as_of: "2026-01-05", score: 0.0123 },
  ],
  signals: [
    {
      kind: "funding_granted",
      occurred_on: null,
      available_on: "2025-09-01",
      note: "BEW Modul 2",
      url: "https://example.org/bew",
    },
    {
      kind: "council_decision",
      occurred_on: "2025-05-28",
      available_on: "2025-06-01",
      note: "Wärmenetz Bahnstadt Süd",
      url: null,
    },
  ],
  tenders: [
    {
      origin: "notice",
      kind: "planning",
      status: "awarded",
      title: "Planung Wärmenetz Bahnstadt Süd",
      buyer_name: "Stadtwerke Heidelberg",
      available_on: "2024-03-01",
      published_on: "2024-03-01",
      deadline_on: null,
      awarded_on: "2024-06-01",
      contract_end_on: null,
      framework: false,
      estimated_value_eur: null,
      award_value_eur: 480_000,
      offers: 3,
      winner_name: "Ingenieurbüro Nord",
      url: null,
    },
  ],
};
