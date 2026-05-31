import { useState, useEffect, useRef } from "react";
import Waveform from "../Comp/Waveform";

const getConfidenceColor = (c) => {
  if (!c) return "#94a3b8";
  if (c >= 0.85) return "#16a34a";
  if (c >= 0.6)  return "#b45309";
  return "#dc2626";
};

function parseTranscript(raw, confidences = []) {
  if (!raw) return [];
  return raw
    .split("\n")
    .filter(line => line.trim())
    .map((line, index) => {
      const colonIndex = line.indexOf(": ");
      if (colonIndex === -1) return null;
      const rawSpeaker = line.substring(0, colonIndex).trim();
      const text       = line.substring(colonIndex + 2).trim();
      const speaker    = rawSpeaker === "SPEAKER_0" ? "Doctor" : "Patient";
      const confObj    = confidences[index];
      return {
        speaker,
        text,
        confidence:         confObj?.confidence         ?? null,
        confidence_percent: confObj?.confidence_percent ?? null,
      };
    })
    .filter(Boolean);
}

function formatTime(s) {
  const m   = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function TranscriptPage({ onNavigate, doctorName, patientName, duration, data, audioUrl }) {
  const [playing, setPlaying]         = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [summarizing, setSummarizing] = useState(false);
  const [hoveredLine, setHoveredLine] = useState(null);
  const [audioReady, setAudioReady]   = useState(false);

  const audioRef  = useRef(null);
  const lineRefs  = useRef({});

  const confidences     = data?.sentence_confidences ?? [];
  const durationSeconds = confidences.length > 0
    ? confidences[confidences.length - 1].end
    : 120;
  const transcript = parseTranscript(data?.transcript, confidences);

  // ── Create Audio object once on mount ─────────────────────────────────────
  useEffect(() => {
    if (!audioUrl) return;

    const audio = new Audio();

    audio.addEventListener("canplaythrough", () => setAudioReady(true));
    audio.addEventListener("timeupdate",     () => setCurrentTime(audio.currentTime));
    audio.addEventListener("ended",          () => setPlaying(false));
    audio.addEventListener("error",          (e) => console.error("Audio error:", e));

    audio.src = audioUrl;   // assign src AFTER attaching listeners
    audio.load();
    audioRef.current = audio;

    return () => {
      audio.pause();
      audio.src = "";
      audioRef.current = null;
      setAudioReady(false);
    };
  }, [audioUrl]);

  // ── Play / pause ───────────────────────────────────────────────────────────
  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.play()
        .then(() => setPlaying(true))
        .catch(err => console.error("Playback failed:", err));
    }
  };

  // ── Click a line → seek + play ─────────────────────────────────────────────
  const handleLineClick = (index) => {
    const seg   = confidences[index];
    const audio = audioRef.current;
    if (!seg || !audio) return;

    audio.currentTime = seg.start;
    setCurrentTime(seg.start);

    audio.play()
      .then(() => setPlaying(true))
      .catch(err => console.error("Seek play failed:", err));
  };

  // ── Derive active line ─────────────────────────────────────────────────────
  const activeLine = confidences.length > 0
    ? confidences.findIndex((seg, i) => {
        const next = confidences[i + 1];
        return currentTime >= seg.start && (next ? currentTime < next.start : true);
      })
    : Math.min(
        Math.floor((currentTime / durationSeconds) * transcript.length),
        transcript.length - 1
      );

  // ── Auto-scroll active line ────────────────────────────────────────────────
  useEffect(() => {
    if (playing && activeLine >= 0 && lineRefs.current[activeLine]) {
      lineRefs.current[activeLine].scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [activeLine, playing]);

  const handleSummarize = () => {
    setSummarizing(true);
    setTimeout(() => {
      setSummarizing(false);
      onNavigate("Summary", data);
    }, 800);
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>
      <style>{`
        @keyframes lowConfPulse {
          0%, 100% { box-shadow: 0 0 0 0   rgba(220,38,38,0.0);  }
          50%       { box-shadow: 0 0 0 3px rgba(220,38,38,0.15); }
        }
        .low-conf-line { animation: lowConfPulse 2.5s ease-in-out infinite; }
        .low-conf-line:hover { animation: none; box-shadow: 0 0 0 2px rgba(220,38,38,0.35) !important; }
        .transcript-line { transition: all 0.2s ease; }
        .transcript-line:hover { transform: translateX(2px); }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 40 }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1e3a8a", margin: 0 }}>Consultation Transcript</h1>
          <p style={{ color: "#2563eb", fontWeight: 600, margin: "6px 0 0", fontSize: 16 }}>Doctor: {doctorName}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <p style={{ fontWeight: 700, color: "#1e3a8a", margin: 0 }}>Patient: {patientName}</p>
          <p style={{ fontWeight: 700, color: "#1e3a8a", margin: "4px 0 0" }}>Duration: {duration}</p>
        </div>
      </div>

      {/* Confidence bar */}
      {(() => {
        const lowCount = transcript.filter((_, i) => {
          const conf = confidences[i]?.confidence ?? null;
          return conf !== null && conf < 0.6;
        }).length;
        return (
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "10px 16px", borderRadius: 12, border: "1px solid #e2e8f0",
            background: "#f8fafc", marginBottom: 30, flexWrap: "wrap", gap: 10,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: "#1e3a8a" }}>Transcription Confidence</span>
              {[
                { dot: "#16a34a", label: "High ≥ 85%" },
                { dot: "#b45309", label: "Medium 60–84%" },
                { dot: "#dc2626", label: "Low < 60% – review carefully" },
              ].map(({ dot, label }) => (
                <span key={label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#374151" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0 }} />
                  {label}
                </span>
              ))}
            </div>
            {lowCount > 0 && (
              <span style={{
                fontSize: 13, fontWeight: 700, color: "#dc2626",
                border: "1.5px solid #dc2626", borderRadius: 20,
                padding: "3px 12px", background: "#fff", whiteSpace: "nowrap",
              }}>
                {lowCount} segment{lowCount !== 1 ? "s" : ""} need review
              </span>
            )}
          </div>
        );
      })()}

      {/* Hint */}
      <p style={{ fontSize: 13, color: "#94a3b8", marginBottom: 16, marginTop: -16 }}>
        💡 Click any line to jump playback to that moment. Low-confidence segments are highlighted in red.
      </p>

      {/* Transcript lines */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 70 }}>
        {transcript.map((line, i) => {
          const isActive     = i === activeLine;
          const isDoctor     = line.speaker === "Doctor";
          const conf         = line.confidence ?? 1;
          const isLow        = line.confidence !== null && conf < 0.6;
          const isMed        = line.confidence !== null && conf >= 0.6 && conf < 0.85;
          const isHovered    = hoveredLine === i;
          const seg          = confidences[i];
          const hasTimestamp = seg?.start != null;
          const timestamp    = hasTimestamp ? `[${formatTime(seg.start)}]` : null;

          const getBg = () => {
            if (isActive) return "#e0f2fe";
            if (isLow)    return "#fef2f2";
            if (isMed)    return "#fefce8";
            return "#f8fafc";
          };
          const getBorder = () => {
            if (isActive)           return "1.5px solid #bae6fd";
            if (isLow && isHovered) return "1.5px solid #dc2626";
            if (isLow)              return "1.5px solid #fca5a5";
            return "1.5px solid transparent";
          };

          return (
            <div
              key={i}
              ref={(el) => (lineRefs.current[i] = el)}
              className={`transcript-line${isLow ? " low-conf-line" : ""}`}
              onClick={() => hasTimestamp && handleLineClick(i)}
              onMouseEnter={() => setHoveredLine(i)}
              onMouseLeave={() => setHoveredLine(null)}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "12px 16px", borderRadius: 12,
                background: getBg(), border: getBorder(),
                cursor: hasTimestamp ? "pointer" : "default",
                position: "relative",
              }}
            >
              <span style={{ fontWeight: 700, color: "#1f2937", fontSize: 15, flex: 1 }}>
                {timestamp && (
                  <span style={{ color: "#64748b", fontWeight: 600, marginRight: 6, fontSize: 13 }}>
                    {timestamp}
                  </span>
                )}
                <span style={{ color: isDoctor ? "#1e3a8a" : "#0f766e", marginRight: 4 }}>
                  {line.speaker}:
                </span>
                <span style={{ fontWeight: isActive ? 700 : 600, color: "#1f2937" }}>
                  {line.text}
                </span>
              </span>

              <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, marginLeft: 16 }}>
                {isHovered && hasTimestamp && (
                  <span style={{
                    fontSize: 12, color: "#2563eb", fontWeight: 600,
                    background: "#eff6ff", borderRadius: 6, padding: "2px 8px",
                    border: "1px solid #bfdbfe", whiteSpace: "nowrap",
                  }}>
                    ▶ {formatTime(seg.start)}
                  </span>
                )}
                {line.confidence_percent !== null && (
                  <span style={{
                    fontSize: 12, fontWeight: 700,
                    color: getConfidenceColor(conf),
                    border: `1.5px solid ${getConfidenceColor(conf)}`,
                    borderRadius: 6, padding: "2px 10px",
                    minWidth: 48, textAlign: "center", background: "#fff",
                  }}>
                    {line.confidence_percent}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Controls */}
      <div style={{
        display: "flex", alignItems: "center", gap: 20,
        background: "#f8fafc", borderRadius: 16, padding: "12px 20px",
        border: "1px solid #e2e8f0",
      }}>
        <button
          onClick={togglePlay}
          disabled={!audioReady}
          style={{
            width: 48, height: 48, borderRadius: "50%",
            border: "2px solid #ef4444", background: "#fff",
            cursor: audioReady ? "pointer" : "not-allowed",
            opacity: audioReady ? 1 : 0.4,
            flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          {playing ? (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="#ef4444">
              <rect x="3"  y="2" width="4" height="14" rx="1" />
              <rect x="11" y="2" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="#ef4444">
              <polygon points="4,2 16,9 4,16" />
            </svg>
          )}
        </button>

        <div style={{ flex: 1 }}>
          <Waveform active={playing} duration={durationSeconds} currentTime={currentTime} />
        </div>

        <span style={{ fontSize: 13, color: "#64748b", minWidth: 72, textAlign: "right" }}>
          {formatTime(currentTime)} / {formatTime(durationSeconds)}
        </span>

        <button
          onClick={handleSummarize}
          disabled={summarizing}
          style={{
            padding: "12px 28px", borderRadius: 40, border: "none", cursor: "pointer",
            background: summarizing ? "#93c5fd" : "#2563eb",
            color: "#fff", fontWeight: 700, fontSize: 15,
            fontFamily: "inherit", transition: "background 0.2s",
          }}
        >
          {summarizing ? "Generating…" : "Summarize"}
        </button>
      </div>
    </div>
  );
}