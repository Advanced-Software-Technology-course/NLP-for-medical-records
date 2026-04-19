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

// ── Help popup ────────────────────────────────────────────────────────────────
const HELP_STEPS = [
  { title: "Start Recording", desc: 'Tap "Start Recording" — you\'ll be asked to fill in session details first.' },
  { title: "Fill in Details", desc: "Enter the doctor name, patient name, and date of birth. Other fields are optional." },
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

// ── Session Modal ─────────────────────────────────────────────────────────────
const CONSULTATION_TYPES = ["General", "Follow-up", "Specialist", "Emergency"];
const LANGUAGES = ["English", "Hungarian", "German", "French", "Spanish"];

function SessionModal({ onConfirm, onCancel }) {
  const [form, setForm] = useState({
    doctorName: "",
    patientName: "",
    dob: "",
    consultationType: "",
    language: "English",
  });
  const [errors, setErrors] = useState({});

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const validate = () => {
    const e = {};
    if (!form.doctorName.trim()) e.doctorName = true;
    if (!form.patientName.trim()) e.patientName = true;
    if (!form.dob) e.dob = true;
    return e;
  };

  const handleSubmit = () => {
    const e = validate();
    if (Object.keys(e).length) { setErrors(e); return; }
    onConfirm(form);
  };

  const inputStyle = (key) => ({
    width: "100%", height: 36, padding: "0 10px",
    border: `0.5px solid ${errors[key] ? "#ef4444" : "rgba(0,0,0,0.2)"}`,
    borderRadius: 8, fontSize: 14, fontFamily: "inherit",
    background: "transparent", color: "inherit", outline: "none",
    boxShadow: errors[key] ? "0 0 0 2px rgba(239,68,68,0.15)" : "none",
  });

  const labelStyle = {
    display: "block", fontSize: 12, fontWeight: 500,
    color: "#64748b", marginBottom: 5, letterSpacing: "0.02em",
  };

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      background: "rgba(15,23,42,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 16,
    }}>
      <div style={{
        background: "#fff", borderRadius: 20, padding: "28px 28px 24px",
        width: "100%", maxWidth: 400, maxHeight: "90vh", overflowY: "auto",
        boxShadow: "0 8px 48px rgba(30,58,138,0.12)",
      }}>
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1e3a8a" }}>
            Session details
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>
            Fill in the required fields before the recording begins.
          </p>
        </div>

        {/* Doctor name */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>
            Doctor name <span style={{ color: "#ef4444" }}>*</span>
          </label>
          <input
            style={inputStyle("doctorName")}
            placeholder="Dr. Jane Smith"
            value={form.doctorName}
            onChange={set("doctorName")}
            onFocus={() => setErrors((e) => ({ ...e, doctorName: false }))}
          />
        </div>

        {/* Patient name */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>
            Patient full name <span style={{ color: "#ef4444" }}>*</span>
          </label>
          <input
            style={inputStyle("patientName")}
            placeholder="John Doe"
            value={form.patientName}
            onChange={set("patientName")}
            onFocus={() => setErrors((e) => ({ ...e, patientName: false }))}
          />
        </div>

        {/* DOB */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>
            Date of birth <span style={{ color: "#ef4444" }}>*</span>
          </label>
          <input
            type="date"
            style={inputStyle("dob")}
            value={form.dob}
            onChange={set("dob")}
            onFocus={() => setErrors((e) => ({ ...e, dob: false }))}
          />
        </div>

        {/* Divider + optional section */}
        <hr style={{ border: "none", borderTop: "0.5px solid rgba(0,0,0,0.1)", margin: "16px 0 12px" }} />
        <p style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 }}>
          Optional
        </p>

        {/* Consultation type + Language row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 20 }}>
          <div>
            <label style={labelStyle}>Consultation type</label>
            <select style={{ ...inputStyle(), padding: "0 8px" }} value={form.consultationType} onChange={set("consultationType")}>
              <option value="">Select…</option>
              {CONSULTATION_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Language</label>
            <select style={{ ...inputStyle(), padding: "0 8px" }} value={form.language} onChange={set("language")}>
              {LANGUAGES.map((l) => <option key={l}>{l}</option>)}
            </select>
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 38, borderRadius: 40,
              border: "0.5px solid rgba(0,0,0,0.15)",
              background: "transparent", fontSize: 14, fontWeight: 600,
              color: "#64748b", cursor: "pointer", fontFamily: "inherit",
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            style={{
              flex: 2, height: 38, borderRadius: 40, border: "none",
              background: "#2563eb", color: "#fff",
              fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
            }}
          >
            Start recording →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function HomePage({ onNavigate, onDurationSave, onDataReceived }) {
  const [recording, setRecording]   = useState(false);
  const [seconds, setSeconds]       = useState(0);
  const [showHelp, setShowHelp]     = useState(false);
  const [showModal, setShowModal]   = useState(false);
  const [generating, setGenerating] = useState(false);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef   = useRef([]);
  const secondsRef       = useRef(0);
  const sessionDataRef   = useRef(null);

  useEffect(() => {
    let interval = null;
    if (recording) {
      interval = setInterval(() => {
        setSeconds(s => {
          const next = s + 1;
          secondsRef.current = next;
          return next;
        });
      }, 1000);
    } else {
      clearInterval(interval);
    }
    return () => clearInterval(interval);
  }, [recording]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = () => handleUpload();

      mediaRecorderRef.current.start();
      setRecording(true);
      setSeconds(0);
      secondsRef.current = 0;
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("Could not access microphone. Please ensure you have granted permission.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      setRecording(false);
    }
  };

  const handleUpload = async () => {
    setGenerating(true);

    const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
    const formData  = new FormData();
    formData.append("file", audioBlob, "recording.wav");

    if (sessionDataRef.current) {
      formData.append("sessionData", JSON.stringify(sessionDataRef.current));
    }

    try {
      const response = await fetch("http://localhost:5000/api/process", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        const s  = secondsRef.current;
        const mm = String(Math.floor(s / 60)).padStart(2, "0");
        const ss = String(s % 60).padStart(2, "0");
        onDurationSave(`${mm}:${ss}`);

        if (onDataReceived) onDataReceived(data.data);

        onNavigate("Transcript");
      } else {
        alert(`Error: ${data.error || "Failed to process audio"}`);
      }
    } catch (error) {
      console.error("Upload failed", error);
      alert("Network error. Is the backend running?");
    } finally {
      setGenerating(false);
    }
  };

  // Called when user submits the session modal — saves data then starts recording
  const handleModalConfirm = async (formData) => {
    sessionDataRef.current = formData;
    setShowModal(false);
    await startRecording();
  };

  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 40 }}>

      <RecordingCircle seconds={seconds} />

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {!recording ? (
            <button
              onClick={() => setShowModal(true)}   // ← opens modal, not startRecording directly
              disabled={generating}
              style={{
                padding: "14px 48px", borderRadius: 40, border: "none", cursor: "pointer",
                background: "#2563eb",
                color: "#fff", fontWeight: 700, fontSize: 16, fontFamily: "inherit",
                transition: "all 0.2s",
                opacity: generating ? 0.5 : 1,
              }}
            >
              Start Recording
            </button>
          ) : (
            <button
              onClick={stopRecording}
              style={{
                padding: "14px 48px", borderRadius: 40, border: "none", cursor: "pointer",
                background: "#1e40af",
                color: "#fff", fontWeight: 700, fontSize: 16, fontFamily: "inherit",
                boxShadow: "0 0 0 4px rgba(37,99,235,0.25)",
                display: "flex", alignItems: "center", gap: 10,
              }}
            >
              <div style={{ width: 12, height: 12, background: "#ef4444", borderRadius: 2 }} />
              Stop Recording
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
            Processing audio... this may take a moment
          </p>
        )}
      </div>

      {/* Session modal */}
      {showModal && (
        <SessionModal
          onConfirm={handleModalConfirm}
          onCancel={() => setShowModal(false)}
        />
      )}

      {/* Help popup — rendered once */}
      {showHelp && <HelpPopup onClose={() => setShowHelp(false)} />}

      {/* Help FAB */}
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
    </div>
  );
}