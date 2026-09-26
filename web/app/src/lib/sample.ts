import type { Evidence, Valuation } from "../api";

/** The prototype's example report (Harbourline Logistics), shown at /v/sample without calling the API. */
export const SAMPLE: Valuation = {
  id: "sample",
  url: "https://harbourline.com.au",
  status: "approved",
  steps: [
    { key: "read_site", status: "done", detail: "14 pages", at: "0:18" },
    { key: "profile", status: "done", detail: "Harbourline Logistics Pty Ltd", at: "0:31" },
    { key: "competitors", status: "done", detail: "9 found", at: "1:02" },
    { key: "market", status: "done", detail: "23 sources", at: "1:40" },
    { key: "svi", status: "done", detail: "SVI 66.7", at: "2:05" },
    { key: "narrative", status: "done", detail: null, at: "2:21" },
  ],
  counters: { pages: 14, competitors: 9, sources: 23 },
  profile: { name: "Harbourline Logistics" },
  competitors: [
    { name: "Shipit Freight", raised_aud: 12_000_000, sources: 4 },
    { name: "Loadlink AU", raised_aud: 5_500_000, sources: 3 },
    { name: "Freightmate", raised_aud: 3_200_000, sources: 2 },
    { name: "Cargo Hub", raised_aud: 1_100_000, sources: 2 },
  ],
  svi: {
    index: 66.7,
    band: "B",
    dimensions: {
      founder_quality: { score: 72, basis: "ai_suggested" }, product_strength: { score: 68, basis: "ai_suggested" }, market_attractiveness: { score: 74, basis: "ai_suggested" },
      revenue_performance: { score: 55, basis: "computed" }, growth_capability: { score: 61, basis: "computed" }, investment_readiness: { score: 70, basis: "ai_suggested" }, trust_verification: { score: 64, basis: "ai_suggested" },
    },
    weights: { founder_quality: 0.2, product_strength: 0.15, market_attractiveness: 0.2, revenue_performance: 0.2, growth_capability: 0.1, investment_readiness: 0.1, trust_verification: 0.05 },
    valuation_low_aud: 2_400_000,
    valuation_mid_aud: 3_360_000,
    valuation_high_aud: 4_300_000,
    method: "revenue × cited sector multiple (low · median · high) × SVI factor 1.17",
    narrative: "Example data. Harbourline runs a B2B freight-booking platform with recurring revenue. The founding team has logistics and software backgrounds; the market is growing and well cited. Revenue concentration and a short audited history keep the score in grade B.",
  },
  error: null,
};

export const SAMPLE_EVIDENCE: Evidence[] = [
  { url: "https://asic.gov.au", title: "ASIC company register", snippet: "Example source: registration and officeholders.", retrieved_at: null },
  { url: "https://www.ibisworld.com", title: "IBISWorld industry report", snippet: "Example source: sector size and growth.", retrieved_at: null },
  { url: "https://www.crunchbase.com", title: "Crunchbase competitor funding", snippet: "Example source: capital raised by competitors.", retrieved_at: null },
  { url: "https://www.afr.com", title: "Australian Financial Review", snippet: "Example source: press coverage.", retrieved_at: null },
];
