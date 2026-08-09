import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export const incidentKeys = {
  all: ["incidents"] as const,
  detail: (id: string) => ["incident", id] as const,
  timeline: (id: string) => ["incident", id, "timeline"] as const,
  facts: (id: string) => ["incident", id, "facts"] as const,
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