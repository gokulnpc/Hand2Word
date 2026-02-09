"use client";
import React from "react";

export default function Tabs({
  tabs,
  current,
  onChange,
}: {
  tabs: string[];
  current: string;
  onChange: (t: string) => void;
}) {
  return (
    // This style is already excellent and fits the theme.
    <div className="inline-flex rounded-xl bg-white/[0.06] border border-white/10 backdrop-blur p-1 shadow-xl">
      {tabs.map((t) => {
        const active = current === t;
        return (
          <button
            key={t}
            onClick={() => onChange(t)}
            className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition
              ${active ? "bg-white text-black shadow-md" : "text-white/70 hover:bg-white/10"}
            `}
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}