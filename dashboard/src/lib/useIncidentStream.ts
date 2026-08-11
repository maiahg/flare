"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { incidentKeys } from "./hooks";

export function useIncidentStream(incidentId: string) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!incidentId) return;
    const source = new EventSource(
      `/api/v1/incidents/${incidentId}/stream`,
    );

    const invalidate = () => {
      // Prefix match: refetch every query for this incident.
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      queryClient.invalidateQueries({ queryKey: incidentKeys.all });
    };

    source.addEventListener("memory.updated", invalidate);
    source.addEventListener("summary.updated", invalidate);

    return () => {
      source.removeEventListener("memory.updated", invalidate);
      source.removeEventListener("summary.updated", invalidate);
      source.close();
    };
  }, [incidentId, queryClient]);
}
