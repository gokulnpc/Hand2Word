"use client";
import React, { useState } from "react";
import Tabs from "@/components/autocorrect/Tabs";
import SettingsTab from "@/components/autocorrect/SettingsTab";
import LiveTab from "@/components/autocorrect/LiveTab";

export default function ASLAutoCorrectApp() {
  const [tab, setTab] = useState<"Settings" | "Live">("Live");
  return (
    // Use the signature dark background from the training app
    <main className="min-h-screen bg-neutral-950 text-white">
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        {/* Styled header for a more polished look */}
        <header className="flex items-center justify-between gap-4 border-b border-white/10 pb-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              ASL Autocorrect Agent
            </h1>
            <p className="text-sm text-white/60 mt-1">
              Live landmark processing and word suggestions.
            </p>
          </div>
          <Tabs
            tabs={["Live", "Settings"]}
            current={tab}
            onChange={(t) => setTab(t as any)}
          />
        </header>

        {tab === "Settings" ? <SettingsTab /> : <LiveTab />}
      </div>
    </main>
  );
}