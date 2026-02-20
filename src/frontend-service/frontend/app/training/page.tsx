"use client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { loadScript, drawLandmarkCircle } from "@/lib/utils";

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

/** ---------- constants ---------- */
const CONFIDENCE_THRESHOLD = 0.5;
const LETTER_DWELL_MS = 450;
const WS_URL = "ws://localhost:8000/api/asl/predict";
type WsState = "idle" | "connecting" | "connected" | "error" | "disconnected";

const WORDS = {
  easy: ["ACT", "AIR", "ART", "BAD", "CAR", "CAT", "FIG", "HAT", "RAT", "WAR"],
  medium: [
    "BRAG",
    "CARD",
    "CHAT",
    "DARK",
    "FILM",
    "GIFT",
    "GRID",
    "RAID",
    "TRIM",
    "WAIT",
  ],
  hard: [
    "ADMIT",
    "ALARM",
    "BRAID",
    "CHAIR",
    "DRAFT",
    "GRAFT",
    "MAGIC",
    "PILAR",
    "TRACK",
    "TRAIT",
  ],
} as const;
type Difficulty = keyof typeof WORDS;
type Mode = "practice" | "challenge";
type Prediction = { letter: string; confidence: number } | null;

const getSignImage = (letter: string) =>
  `https://lifeprint.com/asl101/fingerspelling/abc-gifs/${letter.toLowerCase()}.gif`;

/** ===================================================================== */
export default function Page() {
  const handsReady = useHandsLoader();

  // Refs
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const activeRef = useRef(false);
  const sessionRef = useRef(0);

  // WebSocket (auto-connect)
  const wsRef = useRef<WebSocket | null>(null);
  const lastSent = useRef(0);
  const [wsStatus, setWsStatus] = useState<WsState>("idle");
  const [sessionId] = useState(() => `session_${Date.now()}`);

  // Game state
  const [mode, setMode] = useState<Mode>("practice");
  const [difficulty, setDifficulty] = useState<Difficulty>("easy");
  const wordsPool = useMemo(() => WORDS[difficulty], [difficulty]);
  const [targetWord, setTargetWord] = useState("");
  const [targetIndex, setTargetIndex] = useState(0);
  const [score, setScore] = useState(0);
  const [round, setRound] = useState(1);
  const [timerMs, setTimerMs] = useState(0);
  const timerRef = useRef<number | null>(null);
  const [gameActive, setGameActive] = useState(false); // start active to begin streaming

  // HUD
  const [detected, setDetected] = useState<Prediction>(null);

  // Coaching tips
  const [coachTip, setCoachTip] = useState("");
  const [allCoachTips, setAllCoachTips] = useState<Record<
    string,
    string[]
  > | null>(null);
  const coachTipTimerRef = useRef<any>(null);
  const coachTipIndexRef = useRef<number>(0);

  // Time out
  const detectionTimeoutRef = useRef<any>(null);

  useEffect(() => {
    fetch("/comment.json")
      .then((response) => response.json())
      .then((data) => setAllCoachTips(data))
      .catch((error) => console.error("Failed to load coaching tips:", error));
  }, []);

  // This is the CORRECT "Reset" hook
  useEffect(() => {
    // This effect's ONLY job is to clean up when the target letter changes.

    // 1. Clear any lingering timers from the previous letter.
    if (coachTipTimerRef.current) {
      clearTimeout(coachTipTimerRef.current);
    }
    // 2. Reset the tip to be blank for the new letter.
    setCoachTip("");
    // 3. Reset the tip index, so the next cycle starts from the beginning.
    coachTipIndexRef.current = 0;
  }, [targetWord, targetIndex, gameActive]); // Note the simplified dependency array.

  // This effect TRIGGERS the coach's timer based on hand detection.
  // This is the NEW, corrected code
  useEffect(() => {
    // Exit immediately if the game isn't active or tips haven't loaded yet.
    if (!gameActive || !allCoachTips) {
      return;
    }

    // --- THIS IS THE NEW LOGIC ---
    // If no hand is detected:
    if (!detected) {
      // 1. Immediately clear any pending tip timer.
      if (coachTipTimerRef.current) {
        clearTimeout(coachTipTimerRef.current);
      }
      // 2. Hide the currently displayed tip.
      setCoachTip("");
      // 3. Reset the tip state machine to "waiting for hand".
      coachTipIndexRef.current = 0;
      return; // Stop execution here.
    }
    
    // --- This is the existing logic, which now only runs if a hand IS detected ---
    // If a hand is detected AND we haven't started the timer yet...
    if (coachTipIndexRef.current === 0) {
      // Immediately "flip the switch" to 1 so this block doesn't re-run.
      coachTipIndexRef.current = 1;

      const showNextTip = () => {
        const currentLetter = targetWord[targetIndex];
        const tipsForLetter = allCoachTips[currentLetter];

        if (tipsForLetter && tipsForLetter.length > 0) {
          // Use (index - 1) because we flipped the switch to 1 before the first tip.
          const tipToShow =
            tipsForLetter[(coachTipIndexRef.current - 1) % tipsForLetter.length];
          setCoachTip(tipToShow);
          
          coachTipIndexRef.current += 1; // Increment for the next cycle

          // Subsequent tips appear faster.
          coachTipTimerRef.current = setTimeout(showNextTip, 2500);
        }
      };

      // Start the timer for the very FIRST tip with a long delay.
      coachTipTimerRef.current = setTimeout(showNextTip, 4500);
    }
  }, [detected, allCoachTips, gameActive, targetWord, targetIndex]);

  // Stabilization
  const stableRef = useRef<{
    letter: string | null;
    since: number;
    lastEmitted: string | null;
  }>({
    letter: null,
    since: 0,
    lastEmitted: null,
  });

  // Add this near your other refs
  const predictionHandlerRef = useRef<(pred: Prediction) => void>(() => {});

  useEffect(() => {
    predictionHandlerRef.current = (pred: Prediction) => handlePrediction(pred);
  });

  const startRound = (newRound: number) => {
    const next = wordsPool[Math.floor(Math.random() * wordsPool.length)];
    console.log("next word:", next);
    setTargetWord(next);
    setTargetIndex(0);
    setRound(newRound);
    setTimerMs(0);
  };

  /** ---------- WebSocket: auto-connect + simple retry ---------- */
  useEffect(() => {
    let retryTimer: any;
    const connect = () => {
      try {
        setWsStatus("connecting");
        const ws = new WebSocket(WS_URL);
        ws.onopen = () => setWsStatus("connected");
        ws.onclose = () => {
          setWsStatus("disconnected");
          retryTimer = setTimeout(connect, 30000); // simple reconnect
        };
        ws.onerror = () => setWsStatus("error");
        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data);
            if (msg?.prediction && typeof msg.prediction === "string") {
              const match = msg.prediction.match(/[A-Z]$/);
              if (match) {
                const letter = match[0];
                const confidence = Number(msg.confidence ?? 0);
                const incoming: Prediction = {
                  letter,
                  confidence: isFinite(confidence) ? confidence : 0,
                };

                // 1. Update the UI with the new detection
                setDetected(incoming);

                // 2. Pass it to the game logic handler
                predictionHandlerRef.current(incoming);

                // 3. Manage the timeout to hide the chip if predictions stop
                if (detectionTimeoutRef.current) {
                  clearTimeout(detectionTimeoutRef.current);
                }
                detectionTimeoutRef.current = setTimeout(() => {
                  setDetected(null);
                }, 500); // Hide the chip after 500ms of no new predictions
              }
            }
          } catch {}
        };
        wsRef.current = ws;
      } catch (e) {
        console.error(e);
        setWsStatus("error");
      }
    };
    connect();
    return () => {
      clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;

      if (detectionTimeoutRef.current)
        clearTimeout(detectionTimeoutRef.current);
    };
  }, []);

  /** ---------- MediaPipe Hands: start/stop camera & stream ---------- */
  useEffect(() => {
    if (!gameActive || !handsReady) return;
    const mySession = ++sessionRef.current;
    activeRef.current = true;

    const videoEl = videoRef.current!;
    const canvasEl = canvasRef.current!;
    const ctx = canvasEl.getContext("2d")!;

    const syncSize = () => {
      const rect = videoEl.getBoundingClientRect();
      const dpr = devicePixelRatio || 1;
      canvasEl.width = Math.max(1, Math.floor(rect.width * dpr));
      canvasEl.height = Math.max(1, Math.floor(rect.height * dpr));
    };

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

      // draw video + landmarks
      ctx.save();
      ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
      ctx.translate(canvasEl.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(results.image, 0, 0, canvasEl.width, canvasEl.height);
      ctx.fillStyle = "#B91048";
      const drawList = (lm?: any[]) =>
        lm?.forEach((pt) => {
          const x = pt.x * canvasEl.width,
            y = pt.y * canvasEl.height;
          drawLandmarkCircle(ctx, x, y);
        });
      (results.multiHandLandmarks || []).forEach((lm: any[]) => drawList(lm));
      ctx.restore();

      // build payload vector (pose/face zeros + two hands)
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

      // prepare landmarks for left and right to send
      const left = leftLM
        ? leftLM.map((p) => [p.x, p.y])
        : Array(21).fill([0, 0]);
      const right = rightLM
        ? rightLM.map((p) => [p.x, p.y])
        : Array(21).fill([0, 0]);

      // const left = flattenLandmarks(leftLM, { includeVisibility: false, points: 21, dimsPerPoint: 2 }); // 3
      // const right = flattenLandmarks(rightLM, { includeVisibility: false, points: 21, dimsPerPoint: 2 }); // 3
      //not include ...poseZeros, ...faceZeros,
      //const vector = [...left, ...right];
      // throttle ~16Hz
      const now = performance.now();
      if (wsRef.current?.readyState === 1 && now - lastSent.current > 60) {
        // wsRef.current.send(JSON.stringify({ action: "sendlandmarks", session_id: sessionId, data: vector }));
        wsRef.current.send(
          JSON.stringify({
            action: "sendlandmarks",
            session_id: sessionId,
            data: right,
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
        } catch {}
      },
      width: 960,
      height: 540,
    });

    camera.start();
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
  }, [gameActive, handsReady, sessionId]);

  /** ---------- timers ---------- */
  useEffect(() => {
    // This effect runs on the first load and whenever `difficulty` changes.
    setScore(0);
    startRound(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [difficulty]); // The key is to run this effect when difficulty changes

  useEffect(() => {
    if (!gameActive) return;
    const start = performance.now();
    const id = requestAnimationFrame(function tick(now) {
      setTimerMs(now - start);
      timerRef.current = requestAnimationFrame(tick);
    });
    return () => {
      if (timerRef.current) cancelAnimationFrame(timerRef.current);
      cancelAnimationFrame(id);
    };
  }, [round, gameActive]);

  /** ---------- prediction handling ---------- */
  const onStableLetter = (letter: string) => {
    const expected = targetWord[targetIndex];
    const isMatch = letter === expected;
    console.log(isMatch, letter, targetWord, targetIndex);
    if (isMatch) {
      // Reset the stabilization logic to prepare for the next letter.
      stableRef.current = { letter: null, since: 0, lastEmitted: null };

      setTargetIndex((i) => i + 1);
      if (targetIndex + 1 >= targetWord.length) {
        setScore(
          (s) =>
            s + 1 + Math.max(0, Math.round(10000 / Math.max(1000, timerMs)))
        );
        setTimeout(() => startRound(round + 1), 600);
      }
    }
  };

  const handlePrediction = (pred: Prediction) => {
    const now = performance.now();
    const st = stableRef.current;
    if (!pred || pred.confidence < CONFIDENCE_THRESHOLD) {
      st.letter = null;
      return;
    }
    const letter = pred.letter.toUpperCase();
    if (st.letter !== letter) {
      st.letter = letter;
      st.since = now;
      return;
    }
    if (now - st.since >= LETTER_DWELL_MS && st.lastEmitted !== letter) {
      st.lastEmitted = letter;
      onStableLetter(letter);
    }
  };

  // (Dev) keyboard simulate
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.length === 1 ? e.key.toUpperCase() : "";
      if (k >= "A" && k <= "Z") {
        const simulated: Prediction = { letter: k, confidence: 0.99 };
        setDetected(simulated);
        handlePrediction(simulated);
      }
    };
    const onUp = () => setDetected(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onUp);
    };
  }, [handlePrediction]);

  const nextNeeded = targetWord[targetIndex] || "✔";
  const isDetectedMatch =
    !!detected && detected.letter.toUpperCase() === nextNeeded;

  /** ---------- UI ---------- */
  return (
    <div className="min-h-screen w-full bg-neutral-950 text-white flex items-center justify-center p-6">
      <div className="w-full max-w-6xl grid gap-6 grid-cols-1 md:grid-cols-[1fr_360px]">
        {/* LEFT: Camera; Coach under it */}
        <div className="flex flex-col gap-4">
          <div
            className={`relative rounded-2xl overflow-hidden shadow-2xl bg-black/40`}
          >
            <div className="relative rounded-2xl overflow-hidden bg-black/40 aspect-video ring-1 ring-white/10">
              <video
                ref={videoRef}
                className="w-full h-full"
                playsInline
                muted
              />
              <canvas
                ref={canvasRef}
                className="absolute inset-0 w-full h-full"
              />
            </div>

            {/* HUD: round + detected chip */}
            <div className="absolute inset-0 pointer-events-none p-4 flex flex-col">
              <div className="text-sm opacity-80">
                Round <span className="font-semibold">{round}</span>
              </div>
              <div className="mt-auto flex items-end justify-end">
                {detected && (
                  <div
                    className={`pointer-events-none mb-1 mr-1 px-3 py-1 rounded-xl border text-lg font-bold ${
                      isDetectedMatch
                        ? "bg-green-500/80 border-green-300 text-black"
                        : "bg-white/80 border-white/70 text-black"
                    }`}
                  >
                    {detected.letter}
                    <span className="ml-2 text-xs opacity-70">
                      {Math.round(((detected.confidence as number) || 0) * 100)}
                      %
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ADD THIS ENTIRE BLOCK for the Start Screen Overlay */}
          {!gameActive && (
            <div className="absolute inset-0 bg-neutral-900/70 backdrop-blur-md flex flex-col items-center justify-center p-8 text-center z-10">
              <h1 className="text-4xl font-bold tracking-tight mb-3">
                ASL Fingerspelling
              </h1>
              <p className="text-lg text-neutral-300 mb-8">
                Ready to test your skills?
              </p>

              <div className="bg-white/5 border border-white/10 p-4 rounded-lg text-left mb-8 max-w-sm">
                <h2 className="font-semibold mb-2 text-center">How to Play</h2>
                <ul className="space-y-2 text-sm text-neutral-300 list-disc list-inside">
                  <li>Choose your difficulty and mode on the right.</li>
                  <li>
                    Position your signing hand clearly in the camera view.
                  </li>
                  <li>Hold each sign steady to spell the target word.</li>
                </ul>
              </div>

              <button
                onClick={() => {
                  setScore(0);
                  startRound(1);
                  setGameActive(true);
                }}
                className="px-10 py-3 text-xl rounded-xl border-2 border-green-300 bg-green-500 text-black font-bold transform hover:scale-105 transition-transform shadow-lg"
              >
                Start Game
              </button>
            </div>
          )}
          {/* END of the new block */}

          {/* Coach under camera */}
          <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
            <div className="text-xs uppercase opacity-70">Coach</div>
            <div className="text-sm opacity-90 min-h-[3em]">
              {" "}
              {/* Added min-h to prevent layout shift */}
              {targetIndex < targetWord.length ? (
                <>{coachTip}</>
              ) : (
                <>Nice! Preparing next word…</>
              )}
            </div>
            <div className="text-[11px] opacity-60">
              (AI-powered tips to improve your form.)
            </div>
          </div>
        </div>

        {/* RIGHT: Next Letter → Target Word → Score, plus WS status pill */}
        <div className="flex flex-col gap-4">
          {/* status pill */}
          <div className="flex justify-end">
            <span
              className={`text-xs px-2 py-1 rounded-full border ${
                wsStatus === "connected"
                  ? "bg-emerald-500/20 border-emerald-400 text-emerald-200"
                  : wsStatus === "connecting"
                  ? "bg-amber-500/20 border-amber-400 text-amber-200"
                  : wsStatus === "error"
                  ? "bg-rose-500/20 border-rose-400 text-rose-200"
                  : "bg-white/10 border-white/20 text-white/70"
              }`}
            >
              WS: {wsStatus}
            </span>
          </div>

          {/* Next Letter (with mode) */}
          <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
            <div className="text-xs uppercase tracking-widest opacity-70">
              Next Letter
            </div>
            <div className="mt-2 flex items-center gap-3">
              <div className="text-5xl font-extrabold tracking-[0.2em]">
                <span className="inline-block px-3 py-1 rounded-xl bg-white/10 border border-white/10">
                  {nextNeeded}
                </span>
              </div>
              {mode === "practice" && nextNeeded !== "✔" && (
                <div className="w-24 h-24 rounded-xl overflow-hidden bg-black/60 border border-white/10 flex items-center justify-center">
                  <img
                    src={getSignImage(nextNeeded)}
                    alt={`ASL sign for ${nextNeeded}`}
                    className="w-full h-full object-contain"
                  />
                </div>
              )}
            </div>

            <div className="mt-4">
              <div className="text-xs uppercase opacity-70">Mode</div>
              <div className="mt-1 flex gap-2">
                {(["practice", "challenge"] as Mode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={`px-3 py-1 rounded-full text-sm border ${
                      mode === m
                        ? "bg-white text-black"
                        : "bg-transparent text-white"
                    } border-white/20`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Target Word (and difficulty + controls) */}
          <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase opacity-70">Target Word</div>
              <div className="flex gap-2">
                {(["easy", "medium", "hard"] as Difficulty[]).map((d) => (
                  <button
                    key={d}
                    onClick={() => {
                      setDifficulty(d);
                    }}
                    className={`px-3 py-1 rounded-full text-xs border ${
                      difficulty === d
                        ? "bg-white text-black"
                        : "bg-transparent text-white"
                    } border-white/20`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
            <div className="text-3xl font-extrabold tracking-[0.2em]">
              {targetWord.split("").map((ch, i) => (
                <span
                  key={i}
                  className={`px-1 ${i < targetIndex ? "text-green-400" : ""}`}
                >
                  {ch}
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => startRound(round + 1)}
                className="px-4 py-2 rounded-xl border border-white/20 bg-white text-black font-medium"
              >
                Skip ↦
              </button>
              <button
                onClick={() => {
                  setScore(0);
                  startRound(1);
                }}
                className="px-4 py-2 rounded-xl border border-white/20 bg-transparent text-white"
              >
                Reset
              </button>

              {/* Only show End Game button when active */}
              {gameActive && (
                <button
                  onClick={() => setGameActive(false)}
                  className="ml-auto px-4 py-2 rounded-xl border border-white/20 bg-red-600 text-white"
                >
                  End Game
                </button>
              )}
            </div>
          </div>

          {/* Score */}
          <div className="rounded-2xl p-5 bg-white/5 border border-white/10 shadow-xl">
            <div className="text-xs uppercase opacity-70">Score</div>
            <div className="text-2xl font-bold">{score}</div>
            <div className="mt-2 text-xs opacity-70">
              Time: {(timerMs / 1000).toFixed(1)}s
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
