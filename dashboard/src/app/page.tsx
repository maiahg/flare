"use client";

import Link from "next/link";

import { useIncidents } from "@/lib/hooks";

export default function HomePage() {
  const { data, isLoading, isError } = useIncidents();

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600, marginBottom: "1rem" }}>
        Incidents
      </h1>
      {isLoading ? <p>Loading…</p> : null}
      {isError ? <p>Failed to load incidents.</p> : null}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {(data ?? []).map((incident) => (
          <li key={incident.id} style={{ padding: "0.5rem 0" }}>
            <Link href={`/incidents/${incident.id}`}>
              {incident.title}{" "}
              <span style={{ opacity: 0.6 }}>({incident.status})</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}