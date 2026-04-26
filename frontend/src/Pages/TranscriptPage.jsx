import { useState, useEffect, useRef, useCallback } from "react";
import Waveform from "../Comp/Waveform";

const getConfidenceColor = (c) => {
  if (!c) return "#94a3b8";
  if (c >= 0.85) return "#16a34a"; // green
  if (c >= 0.6)  return "#b45309"; // amber/brown
  return "#dc2626";                // red
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
      const text = line.substring(colonIndex + 2).trim();
      const speaker = rawSpeaker === "SPEAKER_0" ? "Doctor" : "Patient";
      const confObj = confidences[index];
      return {
        speaker,
        text,
        confidence: confObj?.confidence ?? null,
        confidence_percent: confObj?.confidence_percent ?? null,
      };
    })
    .filter(Boolean);
}

function formatTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function TranscriptPage({ onNavigate, doctorName, patientName, duration, data }) {
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [summarizing, setSummarizing] = useState(false);

  const animFrameRef = useRef(null);
  const lastTimestampRef = useRef(null);
  const currentTimeRef = useRef(0);

  const confidences = data?.sentence_confidences ?? [];

  // Real duration from last utterance's end time
  const durationSeconds = confidences.length > 0
    ? confidences[confidences.length - 1].end
    : 120;

  const transcript = parseTranscript(data?.transcript, confidences);

  // Derive active line from exact start/end timestamps
  const activeLine = confidences.length > 0
    ? confidences.findIndex((seg, i) => {
        const next = confidences[i + 1];
        return currentTime >= seg.start && (next ? currentTime < next.start : true);
      })
    : Math.min(
        Math.floor((currentTime / durationSeconds) * transcript.length),
        transcript.length - 1
      );

  const tick = useCallback((ts) => {
    if (lastTimestampRef.current !== null) {
      const delta = (ts - lastTimestampRef.current) / 1000;
      currentTimeRef.current = Math.min(currentTimeRef.current + delta, durationSeconds);
      setCurrentTime(currentTimeRef.current);
    }
    lastTimestampRef.current = ts;

    if (currentTimeRef.current < durationSeconds) {
      animFrameRef.current = requestAnimationFrame(tick);
    } else {
      setPlaying(false);
      lastTimestampRef.current = null;
    }
  }, [durationSeconds]);

  useEffect(() => {
    if (playing) {
      if (currentTimeRef.current >= durationSeconds) {
        currentTimeRef.current = 0;
        setCurrentTime(0);
      }
      lastTimestampRef.current = null;
      animFrameRef.current = requestAnimationFrame(tick);
    } else {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      lastTimestampRef.current = null;
    }
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [playing, tick, durationSeconds]);

  const handleSummarize = () => {
    setSummarizing(true);
    setTimeout(() => {
      setSummarizing(false);
      onNavigate("Summary", data);
    }, 800);
  };
 

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>
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
{/* Confidence  Bar */}
{(() => {
  const lowCount = transcript.filter((_, i) => {
    const conf = confidences[i]?.confidence ?? null;
    return conf !== null && conf < 0.6;
  }).length;

  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "10px 16px",
      borderRadius: 12,
      border: "1px solid #e2e8f0",
      background: "#f8fafc",
      marginBottom: 30,
      flexWrap: "wrap",
      gap: 10,
    }}>
      {/* Left: label + thresholds */}
      <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: "#1e3a8a" }}>
          Transcription Confidence
        </span>
        {[
          { dot: "#16a34a", label: "High ≥ 85%" },
          { dot: "#b45309", label: "Medium  60 – 84%" },
          { dot: "#dc2626", label: "Low < 60% – review carefully" },
        ].map(({ dot, label }) => (
          <span key={label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#374151" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0 }} />
            {label}
          </span>
        ))}
      </div>

      {/* Right: segments needing review */}
      {lowCount > 0 && (
        <span style={{
          fontSize: 13,
          fontWeight: 700,
          color: "#dc2626",
          border: "1.5px solid #dc2626",
          borderRadius: 20,
          padding: "3px 12px",
          background: "#fff",
          whiteSpace: "nowrap",
        }}>
          {lowCount} segment{lowCount !== 1 ? "s" : ""} need review
        </span>
      )}
    </div>
  );
})()}
      {/* Transcript Lines */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 70 }}>
       {transcript.map((line, i) => {
  const isActive = i === activeLine;
  const isDoctor = line.speaker === "Doctor";
  const conf = line.confidence ?? 1;

  // Background color based on confidence
  const getBg = () => {
    if (line.confidence === null) return isActive ? "#e0f2fe" : "#f8fafc";
    if (conf >= 0.85) return isActive ? "#e0f2fe" : "#f8fafc";
    if (conf >= 0.6)  return "#fefce8"; // yellow
    return "#fef2f2"; // red/pink
  };

  // Format timestamp from start time
  const seg = confidences[i];
  const timestamp = seg?.start != null
    ? `[${formatTime(seg.start)}]`
    : null;

  return (
    <div
      key={i}
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "12px 16px",
        borderRadius: 12,
        background: getBg(),
        border: isActive ? "1.5px solid #bae6fd" : "1.5px solid transparent",
        transition: "all 0.3s ease",
      }}
    >
      <span style={{ fontWeight: 700, color: "#1f2937", fontSize: 15 }}>
        {timestamp && (
          <span style={{ color: "#64748b", fontWeight: 600, marginRight: 6 }}>
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

      {line.confidence_percent !== null && (
        <span style={{
          fontSize: 12,
          fontWeight: 700,
          color: getConfidenceColor(conf),
          border: `1.5px solid ${getConfidenceColor(conf)}`,
          borderRadius: 6,
          padding: "2px 10px",
          minWidth: 48,
          textAlign: "center",
          marginLeft: 16,
          flexShrink: 0,
          background: "#fff",
        }}>
          {line.confidence_percent}%
        </span>
      )}
    </div>
  );
})}
      </div>

      {/* Controls */}
      <div style={{ display: "flex", alignItems: "center", gap: 20, background: "#f8fafc", borderRadius: 16, padding: "12px 20px", border: "1px solid #e2e8f0" }}>
        <button
          onClick={() => setPlaying(p => !p)}
          style={{ width: 48, height: 48, borderRadius: "50%", border: "2px solid #ef4444", background: "#fff", cursor: "pointer", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          {playing ? (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="#ef4444">
              <rect x="3" y="2" width="4" height="14" rx="1" />
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
          style={{ padding: "12px 28px", borderRadius: 40, border: "none", cursor: "pointer", background: summarizing ? "#93c5fd" : "#2563eb", color: "#fff", fontWeight: 700, fontSize: 15, fontFamily: "inherit", transition: "background 0.2s" }}
        >
          {summarizing ? "Generating…" : "Summarize"}
        </button>
      </div>
    </div>
  );
}