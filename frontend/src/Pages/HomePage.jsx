import { useState, useEffect, useRef } from "react";


function RecordingCircle({ seconds }) {
  const mm = String(Math.floor(seconds / 60)).padStart(1, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <>
      <style>{`
        @keyframes pulse {
          0%   { transform: scale(1);    opacity: 1; }
          50%  { transform: scale(1.08); opacity: 0.7; }
          100% { transform: scale(1);    opacity: 1; }
        }
        @keyframes pulseMid {
          0%   { transform: scale(1);    opacity: 1; }
          50%  { transform: scale(1.05); opacity: 0.6; }
          100% { transform: scale(1);    opacity: 1; }
        }
        @keyframes fadeInUp {
          0%   { opacity: 0; transform: translateY(12px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes ellipsis {
          0%   { content: ".";   }
          33%  { content: "..";  }
          66%  { content: "..."; }
        }
        .generating-dots::after {
          content: "";
          animation: ellipsis 1.2s steps(1) infinite;
        }
      `}</style>

      <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 260, height: 260 }}>
        <div style={{
          position: "absolute", inset: 0, borderRadius: "50%",
          background: "radial-gradient(circle, #e0e7ff 0%, #f1f5f9 60%, transparent 100%)",
          animation: "pulse 2s ease-in-out infinite",
        }} />
        <div style={{
          position: "absolute", inset: 24, borderRadius: "50%",
          background: "radial-gradient(circle, #dbeafe 0%, #f8fafc 70%, transparent 100%)",
          animation: "pulseMid 2s ease-in-out infinite 0.3s",
        }} />
        <div style={{
          position: "relative", zIndex: 1,
          width: 140, height: 140, borderRadius: "50%",
          background: "#fff",
          boxShadow: "0 4px 32px rgba(37,99,235,0.10)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span style={{ fontSize: 32, fontWeight: 700, color: "#1e3a8a", fontFamily: "'DM Mono', monospace" }}>
            {mm}:{ss}
          </span>
        </div>
      </div>
    </>
  );
}

//help popup
const HELP_STEPS = [
  { title: "Start Recording", desc: 'Tap "Start Recording" to begin capturing the consultation.' },
  { title: "Timer Runs", desc: "The timer tracks the duration of your recording in real time." },
  { title: "Stop & Proceed", desc: "Hit the red stop button to end the session and go to the transcript." },
  { title: "Review Transcript", desc: "Read through the auto-generated transcript on the next page." },
];

function HelpPopup({ onClose }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 100,
      display: "flex", alignItems: "flex-end", justifyContent: "flex-end",
      padding: 24,
      pointerEvents: "none",
    }}>
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(15,23,42,0.18)",
          backdropFilter: "blur(2px)",
          pointerEvents: "all",
        }}
      />
      <div style={{
        position: "relative", zIndex: 1,
        background: "#fff",
        borderRadius: 20,
        boxShadow: "0 8px 48px rgba(30,58,138,0.15)",
        padding: "28px 28px 24px",
        width: 320,
        marginBottom: 72,
        pointerEvents: "all",
        animation: "fadeInUp 0.25s ease",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#1e3a8a" }}>How to use</h3>
          <button
            onClick={onClose}
            style={{
              background: "#f1f5f9", border: "none", borderRadius: "50%",
              width: 30, height: 30, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 16, color: "#64748b",
            }}
          >✕</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {HELP_STEPS.map((step, i) => (
            <div key={i}>
              <p style={{ margin: 0, fontWeight: 700, fontSize: 14, color: "#1e3a8a" }}>{step.title}</p>
              <p style={{ margin: "2px 0 0", fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>{step.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


export default function HomePage({ onNavigate, onDurationSave }) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [showHelp, setShowHelp] = useState(false);
  const [generating, setGenerating] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    if (recording) {
      timerRef.current = setInterval(() => setSeconds(s => s + 1), 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [recording]);

  const toggle = () => setRecording(r => !r);

  const handleStop = () => {
    setRecording(false);

    const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
    const ss = String(seconds % 60).padStart(2, "0");
    onDurationSave(`${mm}:${ss}`);
    setSeconds(0);
    setGenerating(true);
    setTimeout(() => {
      setGenerating(false);
      onNavigate("Transcript");
    }, 2000);
  };

  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 40 }}>
      <RecordingCircle seconds={seconds} />

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={toggle}
            disabled={generating}
            style={{
              padding: "14px 48px", borderRadius: 40, border: "none", cursor: "pointer",
              background: recording ? "#1e40af" : "#2563eb",
              color: "#fff", fontWeight: 700, fontSize: 16, fontFamily: "inherit",
              boxShadow: recording ? "0 0 0 4px rgba(37,99,235,0.25)" : "none",
              transition: "all 0.2s",
              opacity: generating ? 0.5 : 1,
            }}
          >
            {recording ? "Recording" : "Start Recording"}
          </button>
          {recording && (
            <button
              onClick={handleStop}
              style={{
                width: 48, height: 48, borderRadius: "50%", border: "2px solid #ef4444",
                background: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <div style={{ width: 16, height: 16, background: "#ef4444", borderRadius: 3 }} />
            </button>
          )}
        </div>

        {generating && (
          <p
            className="generating-dots"
            style={{
              margin: 0, fontSize: 14, fontWeight: 600, color: "#2563eb",
              animation: "fadeInUp 0.3s ease",
            }}
          >
            Generating transcript
          </p>
        )}
      </div>

      {/* Help button */}
      <button
        onClick={() => setShowHelp(true)}
        style={{
          position: "fixed", bottom: 28, right: 28,
          width: 44, height: 44, borderRadius: "50%",
          background: "#2563eb", border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 16px rgba(37,99,235,0.35)",
          color: "#fff", fontSize: 20, fontWeight: 700,
          zIndex: 50,
        }}
      >
        ?
      </button>

      {showHelp && <HelpPopup onClose={() => setShowHelp(false)} />}
    </div>
  );
}