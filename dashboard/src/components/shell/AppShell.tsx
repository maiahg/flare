"use client";

import { Suspense } from "react";

import { Sidebar } from "./Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Suspense fallback={<div className="w-56 shrink-0 bg-[var(--sidebar)]" />}>
        <Sidebar />
      </Suspense>
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {children}
      </div>
    </div>
  );
}
