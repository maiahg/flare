import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export const incidentKeys = {
  all: ["incidents"] as const,
  detail: (id: string) => ["incident", id] as const,
  timeline: (id: string) => ["incident", id, "timeline"] as const,
  facts: (id: string) => ["incident", id, "facts"] as const,
  runs: (id: string) => ["incident", id, "runs"] as const,
  run: (id: string, runId: string) => ["incident", id, "run", runId] as const,
  evidence: (id: string) => ["incident", id, "evidence"] as const,
  hypotheses: (id: string) => ["incident", id, "hypotheses"] as const,
  usage: (id: string) => ["incident", id, "usage"] as const,
};

export function useIncidents() {
  return useQuery({
    queryKey: incidentKeys.all,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/incidents");
      if (error) throw new Error("failed to load incidents");
      return data;
    },
  });
}

export function useIncident(id: string) {
  return useQuery({
    queryKey: incidentKeys.detail(id),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/incidents/{incident_id}", {
        params: { path: { incident_id: id } },
      });
      if (error) throw new Error("failed to load incident");
      return data;
    },
  });
}

export function useTimeline(id: string) {
  return useQuery({
    queryKey: incidentKeys.timeline(id),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/timeline",
        { params: { path: { incident_id: id } } },
      );
      if (error) throw new Error("failed to load timeline");
      return data;
    },
  });
}

export function useRuns(id: string) {
  return useQuery({
    queryKey: incidentKeys.runs(id),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/runs",
        { params: { path: { incident_id: id } } },
      );
      if (error) throw new Error("failed to load runs");
      return data;
    },
  });
}

export function useRun(id: string, runId: string | null) {
  return useQuery({
    queryKey: incidentKeys.run(id, runId ?? ""),
    enabled: Boolean(runId),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/runs/{run_id}",
        { params: { path: { incident_id: id, run_id: runId as string } } },
      );
      if (error) throw new Error("failed to load run");
      return data;
    },
  });
}

export function useEvidence(id: string) {
  return useQuery({
    queryKey: incidentKeys.evidence(id),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/evidence",
        { params: { path: { incident_id: id } } },
      );
      if (error) throw new Error("failed to load evidence");
      return data;
    },
  });
}

export function useHypotheses(id: string) {
  return useQuery({
    queryKey: incidentKeys.hypotheses(id),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/hypotheses",
        { params: { path: { incident_id: id } } },
      );
      if (error) throw new Error("failed to load hypotheses");
      return data;
    },
  });
}

export function useUsage(id: string) {
  return useQuery({
    queryKey: incidentKeys.usage(id),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/incidents/{incident_id}/usage",
        { params: { path: { incident_id: id } } },
      );
      if (error) throw new Error("failed to load token usage");
      return data;
    },
  });
}