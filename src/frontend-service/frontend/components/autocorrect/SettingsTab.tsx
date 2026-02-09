"use client";
import React, { useCallback } from "react";
import { useApp } from "@/lib/store";

function uid() {
  return Math.random().toString(36).slice(2);
}

export default function SettingsTab() {
  const uploads = useApp((s) => s.uploads);
  const addUpload = useApp((s) => s.addUpload);
  const setUploadStatus = useApp((s) => s.setUploadStatus);

  const onFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files) return;
      Array.from(files).forEach((f) => {
        const id = uid();
        addUpload({ id, name: f.name, size: f.size, type: f.type, status: "ready" });
      });
      e.currentTarget.value = "";
    },
    [addUpload]
  );

  const simulateUpload = useCallback(
    async (id: string) => {
      setUploadStatus(id, "uploading");
      await new Promise((r) => setTimeout(r, 900));
      setUploadStatus(id, "done");
    },
    [setUploadStatus]
  );

  return (
    <div className="grid lg:grid-cols-2 gap-6">
      <section className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
        <h2 className="text-xs uppercase tracking-widest text-white/70">Upload Word Lists</h2>
        <p className="text-sm text-white/60 mt-2">
          Upload CSV or PDF files that contains list of words use recently.
        </p>

        <label className="mt-4 block">
          <input
            type="file"
            accept=".csv,application/pdf"
            multiple
            onChange={onFileSelect}
            className="hidden"
          />
          <span className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black font-semibold cursor-pointer text-sm">
            Choose Files
          </span>
        </label>
      </section>

      <section className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
        <h2 className="text-xs uppercase tracking-widest text-white/70">Queued Files</h2>
        <div className="mt-4 space-y-2">
          {uploads.length === 0 && (
            <div className="p-4 text-center text-sm text-white/60 rounded-lg bg-black/20 border border-white/10">No files selected.</div>
          )}
          {uploads.map((u) => (
            <div key={u.id} className="p-3 bg-black/20 rounded-lg flex items-center justify-between gap-4 border border-white/10">
              <div>
                <div className="text-sm font-medium">{u.name}</div>
                <div className="text-xs text-white/50">
                  {(u.size / 1024).toFixed(1)} KB • {u.type || "unknown"}
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <span className={`text-xs px-2 py-1 rounded-full ${
                    u.status === "done" ? "bg-emerald-500/15 text-emerald-300" :
                    u.status === "uploading" ? "bg-amber-500/15 text-amber-300" :
                    u.status === "error" ? "bg-rose-500/15 text-rose-300" :
                    "bg-white/10 text-white/80"
                }`}>
                  {u.status}
                </span>
                {u.status === "ready" && (
                  <button
                    onClick={() => simulateUpload(u.id)}
                    className="text-xs px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20"
                  >
                    Upload
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}