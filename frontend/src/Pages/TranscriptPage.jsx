import { useState, useEffect } from "react";
import Waveform from "../Comp/Waveform";

const MOCK_TRANSCRIPT = [
  { time: "00:03", speaker: "Doctor", text: "Hello, how are you feeling today?" },
  { time: "00:07", speaker: "Patient", text: "I have been experiencing chest pain since yesterday." },
  { time: "00:12", speaker: "Doctor", text: "Can you describe the pain?" },
  { time: "00:18", speaker: "Patient", text: "It feels like pressure in the middle of my chest.", highlight: true },
  { time: "00:24", speaker: "Doctor", text: "Does it get worse when you breathe or move?" },
  { time: "00:30", speaker: "Patient", text: "Yes, especially when I walk." },
];

export default function TranscriptPage({ onNavigate, doctorName, patientName, duration, data }) {
  const [playing, setPlaying] = useState(false);
  const [activeLine, setActiveLine] = useState(0);
  const [summarizing, setSummarizing] = useState(false);

  // Parse transcript data
  const transcript = data?.transcript 
    ? data.transcript.split('\n').map((line, i) => {
        const [speaker, ...rest] = line.split(': ');
        return {
          time: `00:${String(Math.min(59, i * 4)).padStart(2, '0')}`, // Mock timestamps
          speaker: speaker.includes('0') ? 'Doctor' : 'Patient', // Simple heuristic
          text: rest.join(': ') || line
        };
      })
    : MOCK_TRANSCRIPT;

  // cycle lines thru while playing
  useEffect(() => {
    if (!playing) return;
    const interval = setInterval(() => {
      setActiveLine(prev => (prev + 1) % transcript.length);
    }, 2000);
    return () => clearInterval(interval);
  }, [playing, transcript]);

  const handleSummarize = () => {
    setSummarizing(true);
    setTimeout(() => { 
        setSummarizing(false); 
        onNavigate("Summary"); 
    }, 800); // reduced delay as data is already there
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>
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

      <div style={{ display: "flex", flexDirection: "column", gap: 18, marginBottom: 70 }}>
        {transcript.map((line, i) => {
          const isActive = i === activeLine;
          return (
            <p
              key={i}
              style={{
                margin: 0,
                lineHeight: 1.6,
                fontWeight: isActive ? 800 : 500,
                color: isActive ? "#1e3a8a" : "#94a3b8",
                fontSize: isActive ? 17 : 14,
                transition: "all 0.35s ease",
              }}
            >
              <span style={{ opacity: 0.6 }}>[{line.time}]</span>{" "}
              <span style={{ fontWeight: isActive ? 900 : 700 }}>{line.speaker}:</span>{" "}
              {line.text}
            </p>
          );
        })}
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 20,
        background: "#f8fafc", borderRadius: 16, padding: "12px 20px",
        border: "1px solid #e2e8f0",
      }}>
        <button
          onClick={() => setPlaying(p => !p)}
          style={{
            width: 48, height: 48, borderRadius: "50%", border: "2px solid #ef4444",
            background: "#fff", cursor: "pointer", flexShrink: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
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
          <Waveform active={playing} />
        </div>
        <button
          onClick={handleSummarize}
          disabled={summarizing}
          style={{
            padding: "12px 28px", borderRadius: 40, border: "none", cursor: "pointer",
            background: summarizing ? "#93c5fd" : "#2563eb",
            color: "#fff", fontWeight: 700, fontSize: 15, fontFamily: "inherit",
            transition: "background 0.2s",
          }}
        >
          {summarizing ? "Generating…" : "Summarize"}
        </button>
      </div>
    </div>
  );
}