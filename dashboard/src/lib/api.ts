import createClient from "openapi-fetch";

import type { components, paths } from "./api-types";

function baseUrl(): string {
  if (typeof window !== "undefined") return "";
  return process.env.FLARE_API_URL ?? "http://localhost:8000";
}

export const api = createClient<paths>({ baseUrl: baseUrl() });

// Convenience aliases for the response shapes the UI renders.
export type Incident = components["schemas"]["IncidentRead"];
export type IncidentDetail = components["schemas"]["IncidentDetail"];
export type TimelineEntry = components["schemas"]["TimelineEntryRead"];
export type Fact = components["schemas"]["FactRead"];
export type Summary = components["schemas"]["SummaryRead"];
export type Run = components["schemas"]["RunRead"];
export type RunDetail = components["schemas"]["RunDetail"];
export type AgentTrace = components["schemas"]["AgentTraceRead"];
export type ToolCall = components["schemas"]["ToolCallRead"];
export type Evidence = components["schemas"]["EvidenceRead"];
export type Hypothesis = components["schemas"]["HypothesisRead"];