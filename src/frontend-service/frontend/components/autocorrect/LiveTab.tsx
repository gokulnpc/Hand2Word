"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "@/lib/store";
import { loadScript, drawLandmarkCircle } from "@/lib/utils";
import { flattenLandmarks } from "@/lib/flatten";

type HandsType = any;

declare global {
  interface Window {
    Hands?: HandsType;
    Camera?: any;
  }
}

function useHandsLoader() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await loadScript(
          "https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js"
        );
        await loadScript(
          "https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js"
        );
        if (mounted) setReady(true);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);
  return ready;
}

const WEBSOCKET_URL = "wss://opcs2s86c2.execute-api.us-east-1.amazonaws.com/dev";

export default function LiveTab() {
  const handsReady = useHandsLoader();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const lastSent = useRef(0);

  const activeRef = useRef(false);
  const sessionRef = useRef(0);

  const [cameraOn, setCameraOn] = useState(false);
  const [wsUrl, setWsUrl] = useState<string>(WEBSOCKET_URL);
  const [sessionId, setSessionId] = useState<string>(
    () => `session_${Date.now()}`
  );
  const wsStatus = useApp((s) => s.wsStatus);
  const setWsStatus = useApp((s) => s.setWsStatus);
  const suggestions = useApp((s) => s.suggestions);
  const setSuggestions = useApp((s) => s.setSuggestions);
  const [recognized, setRecognized] = useState<string>("");

  const connectWS = useCallback(() => {
    try {
      setWsStatus("connecting");
      const ws = new WebSocket(wsUrl);
      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => setWsStatus("disconnected");
      ws.onerror = () => setWsStatus("error");
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg?.type === "resolved_word") {
            const resolved_data = msg.data || {};
            const raw_word = resolved_data.raw_word || "";
            const results = resolved_data.all_results || [];

            if (raw_word) {
              setRecognized(raw_word);
            }

            if (Array.isArray(results)) {
              const newSuggestions = results.map((result: any) => ({
                word: result.surface,
                score: result.atlas_score, // Assuming this is the score you want to display
              }));
              setSuggestions(newSuggestions);
            }

            console.log("\n" + "=".repeat(80));
            console.log("🔤 RESOLVED WORD RECEIVED");
            console.log("=".repeat(80));
            console.log(`Raw word: ${raw_word}`);

            if (results.length > 0) {
              console.log("\nTop 5 Results:");
              // The console.table() function is great for displaying arrays of objects
              console.table(results.slice(0, 5));
            } else {
              console.log("No results (UNRESOLVED)");
            }
          }
        } catch (e) {
          // It's better to log errors for debugging
          console.error("Failed to parse or handle WebSocket message:", e);
        }
      };
      wsRef.current = ws;
    } catch (e) {
      console.error(e);
      setWsStatus("error");
    }
  }, [setWsStatus, setSuggestions, wsUrl]);

  const disconnectWS = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const simulateSuggestions = useCallback(() => {
    const samples = [
      ["aws", "ass", "axis"],
      ["asl", "ask", "asap"],
      ["data", "date", "dada"],
      ["vision", "vision pro", "visionOS"],
    ];
    const pick = samples[Math.floor(Math.random() * samples.length)];
    setSuggestions(
      pick.map((w, i) => ({ word: w, score: Math.max(0, 1 - i * 0.15) }))
    );
  }, [setSuggestions]);

  useEffect(() => {
    if (!handsReady || !cameraOn) return;
    const mySession = ++sessionRef.current;
    activeRef.current = true;
    const videoEl = videoRef.current!;
    const canvasEl = canvasRef.current!;
    const ctx = canvasEl.getContext("2d")!;
    const hands: HandsType = new (window as any).Hands({
      locateFile: (file: string) =>
        `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
    });
    hands.setOptions({
      maxNumHands: 2,
      modelComplexity: 1,
      minDetectionConfidence: 0.7,
      minTrackingConfidence: 0.5,
    });
    hands.onResults((results: any) => {
      if (!activeRef.current || mySession !== sessionRef.current) return;
      ctx.save();
      ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
      ctx.translate(canvasEl.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(results.image, 0, 0, canvasEl.width, canvasEl.height);
      ctx.fillStyle = "#B91048";
      const drawList = (lm?: any[]) =>
        lm?.forEach((pt) => {
          const x = pt.x * canvasEl.width;
          const y = pt.y * canvasEl.height;
          drawLandmarkCircle(ctx, x, y);
        });
      (results.multiHandLandmarks || []).forEach((lm: any[]) => drawList(lm));
      ctx.restore();
      const poseZeros = new Array(33 * 4).fill(0);
      const faceZeros = new Array(468 * 3).fill(0);
      let leftLM: any[] | undefined, rightLM: any[] | undefined;
      const handsLM: any[] = results.multiHandLandmarks || [];
      const handedness: any[] = results.multiHandedness || [];
      handsLM.forEach((lm, idx) => {
        const label =
          handedness?.[idx]?.label || handedness?.[idx]?.categoryName;
        if ((label || "").toLowerCase() === "left") leftLM = lm;
        else if ((label || "").toLowerCase() === "right") rightLM = lm;
        else {
          if (!rightLM) rightLM = lm;
          else if (!leftLM) leftLM = lm;
        }
      });
      const left = flattenLandmarks(leftLM, {
        includeVisibility: false,
        points: 21,
        dimsPerPoint: 3,
      });
      const right = flattenLandmarks(rightLM, {
        includeVisibility: false,
        points: 21,
        dimsPerPoint: 3,
      });
      const vector = [...poseZeros, ...faceZeros, ...left, ...right]; // should be 1662 landmarks
      const now = performance.now();
      if (wsRef.current?.readyState === 1 && now - lastSent.current > 60) {
        wsRef.current.send(
          JSON.stringify({
            action: "sendlandmarks",
            session_id: sessionId,
            data: vector,
          })
        );
        lastSent.current = now;
      }
    });
    const camera = new (window as any).Camera(videoEl, {
      onFrame: async () => {
        if (!activeRef.current || mySession !== sessionRef.current) return;
        try {
          await hands.send({ image: videoEl });
        } catch (e: any) {
          const msg = String(e?.message || e);
          if (msg.includes("SolutionWasm") || msg.includes("deleted object"))
            return;
          console.warn(e);
        }
      },
      width: 960,
      height: 540,
    });
    camera.start();
    const syncSize = () => {
      const rect = videoEl.getBoundingClientRect();
      const dpr = devicePixelRatio || 1;
      canvasEl.width = Math.max(1, Math.floor(rect.width * dpr));
      canvasEl.height = Math.max(1, Math.floor(rect.height * dpr));
    };
    syncSize();
    const ro = new ResizeObserver(syncSize);
    ro.observe(videoEl);
    return () => {
      activeRef.current = false;
      sessionRef.current++;
      try {
        ro.disconnect();
      } catch {}
      try {
        camera.stop();
      } catch {}
      try {
        hands.close();
      } catch {}
    };
  }, [handsReady, cameraOn, sessionId]);

  useEffect(() => () => disconnectWS(), [disconnectWS]);

  return (
    <div className="grid grid-cols-12 gap-6">
      <section className="col-span-12 lg:col-span-7">
        <div className="rounded-2xl bg-white/5 p-5 border border-white/10 shadow-xl">
          <header className="flex items-center justify-between mb-4">
            <div className="text-xs uppercase tracking-widest text-white/70">
              Live Camera
            </div>
            <div className="text-xs uppercase text-white/70">
              {cameraOn ? "Live" : "Paused"}
            </div>
          </header>

          <div className="relative rounded-lg overflow-hidden bg-black/40 aspect-video ring-1 ring-white/10">
            <video ref={videoRef} className="w-full h-full" playsInline muted />
            <canvas
              ref={canvasRef}
              className="absolute inset-0 w-full h-full"
            />
            {!cameraOn && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm">
                <div className="text-sm text-white/70">Camera is off</div>
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              className={`px-4 py-2 rounded-xl text-sm font-semibold border transition ${
                cameraOn
                  ? "bg-red-600 border-red-500/50 text-white"
                  : "bg-green-500 border-green-300 text-black"
              }`}
              onClick={() => setCameraOn((v) => !v)}
              disabled={!handsReady}
            >
              {cameraOn ? "Turn Camera Off" : "Turn Camera On"}
            </button>
            <span className="text-xs text-white/60">
              {handsReady ? "MediaPipe ready" : "Loading MediaPipe…"}
            </span>
          </div>
        </div>
      </section>

      <div className="col-span-12 lg:col-span-5 space-y-4">
        <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
          <h3 className="text-xs uppercase tracking-widest text-white/70">
            Predicted Word
          </h3>
          <p className="text-sm text-white/60 mt-1">
            Edit manually or tap a suggestion below.
          </p>
          <div className="mt-4">
            <input
              value={recognized}
              onChange={(e) => setRecognized(e.target.value)}
              placeholder="e.g. asl"
              className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm w-full"
            />
          </div>
        </div>

        <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
          <h3 className="text-xs uppercase tracking-widest text-white/70">
            Do you mean by one of these?
          </h3>
          <p className="text-sm text-white/60 mt-1">
            Number next to word indicates relevance score. Higher is better.
          </p>
          <div className="mt-3">
            <div className="flex flex-wrap gap-2">
              {suggestions.length === 0 && (
                <div className="text-sm text-white/60">No suggestions yet.</div>
              )}
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  className="px-3 py-1 text-sm rounded-full bg-white/10 border border-white/20 hover:bg-white/20 transition"
                  onClick={() => setRecognized(s.word)}
                  aria-label={`Use suggestion ${s.word}`}
                >
                  {s.word}
                  {typeof s.score === "number" ? (
                    <span className="opacity-60 ml-1.5">{`(${s.score.toFixed(2)})`}</span>
                  ) : (
                    ""
                  )}
                </button>
              ))}
            </div>
            {/* <div className="mt-4">
              <button
                onClick={simulateSuggestions}
                className="px-3 py-1 text-xs rounded-full bg-fuchsia-500/20 border border-fuchsia-400 text-fuchsia-200"
              >
                Simulate
              </button>
            </div> */}
          </div>
        </div>

        <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
          <h3 className="text-xs uppercase tracking-widest text-white/70">
            WebSocket Control
          </h3>
          <div className="mt-3 space-y-3">
            <input
              value={wsUrl}
              onChange={(e) => setWsUrl(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm w-full"
              placeholder="wss://your-endpoint.example/dev"
            />
            <input
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm w-full"
            />
            <div className="flex gap-2">
              <button
                onClick={connectWS}
                className="px-4 py-2 text-sm font-semibold rounded-xl bg-indigo-500 border border-indigo-300 text-white"
              >
                Connect
              </button>
              <button
                onClick={disconnectWS}
                className="px-4 py-2 text-sm rounded-xl bg-white/10 border border-white/20"
              >
                Disconnect
              </button>
            </div>
            <div className="text-sm text-white/70">
              Status:{" "}
              <span
                className={
                  wsStatus === "connected"
                    ? "text-emerald-300"
                    : wsStatus === "connecting"
                    ? "text-amber-300"
                    : wsStatus === "error"
                    ? "text-rose-300"
                    : "text-white/60"
                }
              >
                {wsStatus}
              </span>
            </div>
            <p className="text-[11px] text-white/50 pt-2">
              Payload: <code>pose[132]=0</code> + <code>face[1404]=0</code> +{" "}
              <code>hands[63+63]</code> ⇒ 1662, throttled ~16 Hz.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
