import { expect, test } from "@playwright/test";

/**
 * The M1 proof: manually-inserted memory renders live in the dashboard without
 * a reload.
 *
 * Flow:
 *   1. Seed an incident directly via the API.
 *   2. Load its overview page — timeline count starts at 0.
 *   3. POST a timeline entry through the memory write path (a later PR exposes
 *      a write endpoint; until then this uses the seed helper below).
 *   4. Assert the UI updates via SSE, no reload.
 *
 * This spec needs the full stack up (backend on :8000 with migrated DB +
 * Redis). It is not run in unit CI; see README.
 */
const API = process.env.FLARE_API_URL ?? "http://localhost:8000";

test("incident overview updates live when memory changes", async ({
  page,
  request,
}) => {
  // 1. Seed. (Assumes a test-only seed endpoint or fixture is available; wired
  //    up when the write API lands in PR 5.1.)
  const seed = await request.post(`${API}/api/v1/test/seed-incident`, {
    data: { title: "E2E incident" },
  });
  test.skip(
    seed.status() === 404,
    "seed endpoint not yet available (arrives with the write API in PR 5.1)",
  );
  const { incident_id: incidentId } = await seed.json();

  // 2. Load overview.
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByRole("heading", { name: "E2E incident" })).toBeVisible();
  await expect(page.getByTestId("count-timeline_entries")).toHaveText(/0/);

  // 3. Push a timeline entry via the API.
  await request.post(`${API}/api/v1/test/seed-timeline-entry`, {
    data: { incident_id: incidentId, description: "Deploy 1234 shipped" },
  });

  // 4. The count updates via SSE without a reload.
  await expect(page.getByTestId("count-timeline_entries")).toHaveText(/1/, {
    timeout: 10_000,
  });
});
