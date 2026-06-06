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
  { title: "Start Recording", desc: 'Tap "Start Recording" — you\'ll be asked to give consent first.' },
  { title: "Give Consent", desc: "Confirm you have the patient's permission to record the session." },
  { title: "Fill in Details", desc: "Select the doctor and patient before recording begins." },
  { title: "Stop & Proceed", desc: "Hit the stop button to end the session and go to the transcript." },
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

// ── Consent Modal ─────────────────────────────────────────────────────────────
function ConsentModal({ onConfirm, onCancel }) {
  const [consentChecked, setConsentChecked] = useState(false);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      background: "rgba(15,23,42,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 16,
    }}>
      <div style={{
        background: "#fff", borderRadius: 20, padding: "28px 28px 24px",
        width: "100%", maxWidth: 420, boxShadow: "0 8px 48px rgba(30,58,138,0.12)",
      }}>
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "#1e3a8a" }}>
            Recording Consent
          </h3>
          <p style={{ margin: "8px 0 0", fontSize: 14, color: "#64748b", lineHeight: 1.6 }}>
            Before proceeding, please acknowledge that you have consent to record this consultation.
          </p>
        </div>

        <div style={{
          background: "#f8fafc", borderRadius: 12, padding: 16, marginBottom: 24,
          border: "1px solid #e2e8f0",
        }}>
          <p style={{ margin: 0, fontSize: 13, color: "#475569", lineHeight: 1.6, fontWeight: 500 }}>
            This session will be <strong>recorded and transcribed</strong> for medical documentation purposes. The recording includes:
          </p>
          <ul style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: 13, color: "#475569" }}>
            <li>Audio recording of the consultation</li>
            <li>Automatic transcription and processing</li>
            <li>Storage for medical records</li>
          </ul>
        </div>

        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 24 }}>
          <input
            type="checkbox"
            id="consent-check"
            checked={consentChecked}
            onChange={(e) => setConsentChecked(e.target.checked)}
            style={{ width: 18, height: 18, cursor: "pointer", marginTop: 2, accentColor: "#2563eb", flexShrink: 0 }}
          />
          <label htmlFor="consent-check" style={{ fontSize: 13, color: "#374151", cursor: "pointer", lineHeight: 1.5 }}>
            I have obtained consent from the patient and agree to record this consultation
          </label>
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 40, borderRadius: 40,
              border: "0.5px solid rgba(0,0,0,0.15)",
              background: "transparent", fontSize: 14, fontWeight: 600,
              color: "#64748b", cursor: "pointer", fontFamily: "inherit",
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => consentChecked && onConfirm()}
            disabled={!consentChecked}
            style={{
              flex: 1.5, height: 40, borderRadius: 40, border: "none",
              background: consentChecked ? "#2563eb" : "#cbd5e1",
              color: "#fff", fontSize: 14, fontWeight: 700,
              cursor: consentChecked ? "pointer" : "not-allowed",
              fontFamily: "inherit", transition: "all 0.2s",
            }}
          >
            I Agree →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Session Modal ─────────────────────────────────────────────────────────────
const CONSULTATION_TYPES = ["General", "Follow-up", "Specialist", "Emergency"];
const LANGUAGES = ["English", "Hungarian", "German", "French", "Spanish"];

function SessionModal({ onConfirm, onCancel, onNavigate }) {
  const [doctors, setDoctors] = useState([]);
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    doctorId: "", patientId: "", consultationType: "", language: "English",
  });
  const [errors, setErrors] = useState({});

  useEffect(() => {
    Promise.all([
      fetch("/api/doctors").then(r => r.json()),
      fetch("/api/patients").then(r => r.json()),
    ]).then(([docs, pats]) => {
      setDoctors(Array.isArray(docs) ? docs : []);
      setPatients(Array.isArray(pats) ? pats : []);
    }).catch(() => {
      setDoctors([]);
      setPatients([]);
    }).finally(() => setLoading(false));
  }, []);

  const set = (key) => (e) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    setErrors((e2) => ({ ...e2, [key]: false }));
  };

  const validate = () => {
    const e = {};
    if (!form.doctorId) e.doctorId = true;
    if (!form.patientId) e.patientId = true;
    return e;
  };

  const handleSubmit = () => {
    const e = validate();
    if (Object.keys(e).length) { setErrors(e); return; }
    const doctor  = doctors.find(d => String(d.id) === String(form.doctorId));
    const patient = patients.find(p => String(p.id) === String(form.patientId));
    const doctorName  = doctor  ? [doctor.title,  doctor.first_name,  doctor.last_name].filter(Boolean).join(" ")  : "";
    const patientName = patient ? [patient.title, patient.first_name, patient.last_name].filter(Boolean).join(" ") : "";
    onConfirm({ ...form, doctorName, patientName });
  };

  const selectStyle = (key) => ({
    width: "100%", height: 38, padding: "0 10px",
    border: `0.5px solid ${errors[key] ? "#ef4444" : "rgba(0,0,0,0.2)"}`,
    borderRadius: 8, fontSize: 14, fontFamily: "inherit",
    background: "#fff", color: "#0f172a", outline: "none",
    boxShadow: errors[key] ? "0 0 0 2px rgba(239,68,68,0.15)" : "none",
    cursor: "pointer",
  });

  const labelStyle = {
    display: "block", fontSize: 12, fontWeight: 500,
    color: "#64748b", marginBottom: 5, letterSpacing: "0.02em",
  };

  const emptyHint = (entity, page) => (
    <p style={{ margin: "4px 0 0", fontSize: 12, color: "#94a3b8" }}>
      No {entity}s yet.{" "}
      <button
        onClick={() => { onCancel(); onNavigate(page); }}
        style={{ background: "none", border: "none", color: "#2563eb", fontSize: 12, fontWeight: 600, cursor: "pointer", padding: 0 }}
      >
        Add one →
      </button>
    </p>
  );

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
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1e3a8a" }}>Session details</h3>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>
            Select a doctor and patient before the recording begins.
          </p>
        </div>

        {loading ? (
          <p style={{ color: "#94a3b8", fontSize: 14, textAlign: "center", padding: "20px 0" }}>Loading…</p>
        ) : (
          <>
            <div style={{ marginBottom: 14 }}>
              <label style={labelStyle}>Doctor <span style={{ color: "#ef4444" }}>*</span></label>
              <select style={selectStyle("doctorId")} value={form.doctorId} onChange={set("doctorId")}>
                <option value="">Select doctor…</option>
                {doctors.map(d => (
                  <option key={d.id} value={d.id}>
                    {[d.title, d.first_name, d.last_name].filter(Boolean).join(" ")}
                  </option>
                ))}
              </select>
              {doctors.length === 0 && emptyHint("doctor", "Doctors")}
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={labelStyle}>Patient <span style={{ color: "#ef4444" }}>*</span></label>
              <select style={selectStyle("patientId")} value={form.patientId} onChange={set("patientId")}>
                <option value="">Select patient…</option>
                {patients.map(p => (
                  <option key={p.id} value={p.id}>
                    {[p.title, p.first_name, p.last_name].filter(Boolean).join(" ")}
                    {p.date_of_birth ? ` (${p.date_of_birth})` : ""}
                  </option>
                ))}
              </select>
              {patients.length === 0 && emptyHint("patient", "Patients")}
            </div>

            <hr style={{ border: "none", borderTop: "0.5px solid rgba(0,0,0,0.1)", margin: "16px 0 12px" }} />
            <p style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 }}>
              Optional
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 20 }}>
              <div>
                <label style={labelStyle}>Consultation type</label>
                <select style={{ ...selectStyle(), padding: "0 8px" }} value={form.consultationType} onChange={set("consultationType")}>
                  <option value="">Select…</option>
                  {CONSULTATION_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Language</label>
                <select style={{ ...selectStyle(), padding: "0 8px" }} value={form.language} onChange={set("language")}>
                  {LANGUAGES.map(l => <option key={l}>{l}</option>)}
                </select>
              </div>
            </div>
          </>
        )}

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
            disabled={loading}
            style={{
              flex: 2, height: 38, borderRadius: 40, border: "none",
              background: "#2563eb", color: "#fff",
              fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
              opacity: loading ? 0.5 : 1,
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
  const [recording, setRecording]     = useState(false);
  const [seconds, setSeconds]         = useState(0);
  const [showHelp, setShowHelp]       = useState(false);
  const [showConsent, setShowConsent] = useState(false);
  const [showModal, setShowModal]     = useState(false);
  const [generating, setGenerating]   = useState(false);
  // Live indicator: true while we have been recording for a moment but the mic
  // is still picking up essentially nothing (so the user finds out immediately,
  // not after the whole session).
  const [silentLive, setSilentLive]   = useState(false);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef   = useRef([]);
  const secondsRef       = useRef(0);
  const sessionDataRef   = useRef(null);
  const audioBlobUrlRef  = useRef(null);  // ← stores object URL for playback

  // ── Audio-level monitoring (silent-recording detection) ────────────────────
  const audioContextRef  = useRef(null);
  const analyserRef      = useRef(null);
  const levelRafRef      = useRef(null);
  const soundDetectedRef = useRef(false);  // did we ever hear meaningful audio?
  const peakLevelRef     = useRef(0);      // loudest level seen (0..1)
  const voicedFramesRef  = useRef(0);      // frames above the speech threshold

  // Anything below this RMS level is treated as effectively silence (room noise floor).
  const SILENCE_RMS_THRESHOLD = 0.015;
  // We need at least this many voiced frames to consider the session "not silent".
  const MIN_VOICED_FRAMES = 5;

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

  // Tear down the audio analyser if the component unmounts mid-recording.
  useEffect(() => {
    return () => stopLevelMonitor();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = () => handleUpload();

      // ── Set up live audio-level analysis to detect a silent recording ───────
      soundDetectedRef.current = false;
      peakLevelRef.current = 0;
      voicedFramesRef.current = 0;
      setSilentLive(false);
      startLevelMonitor(stream);

      mediaRecorderRef.current.start();
      setRecording(true);
      setSeconds(0);
      secondsRef.current = 0;

      fetch("http://localhost:5000/api/cpu/start", { method: "POST" }).catch(() => {});

    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("Could not access microphone. Please ensure you have granted permission.");
    }
  };

  // Continuously measure the microphone input level while recording. Updates the
  // live "no sound" hint and records whether any meaningful audio was captured.
  const startLevelMonitor = (stream) => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;  // graceful no-op if Web Audio unsupported

      const audioContext = new AudioCtx();
      const source   = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);

      audioContextRef.current = audioContext;
      analyserRef.current = analyser;

      const buffer = new Uint8Array(analyser.fftSize);

      const tick = () => {
        analyser.getByteTimeDomainData(buffer);
        // Compute RMS of the waveform centred on 128 (silence).
        let sumSquares = 0;
        for (let i = 0; i < buffer.length; i++) {
          const v = (buffer[i] - 128) / 128;
          sumSquares += v * v;
        }
        const rms = Math.sqrt(sumSquares / buffer.length);

        if (rms > peakLevelRef.current) peakLevelRef.current = rms;

        if (rms >= SILENCE_RMS_THRESHOLD) {
          voicedFramesRef.current += 1;
          if (voicedFramesRef.current >= MIN_VOICED_FRAMES) {
            soundDetectedRef.current = true;
          }
        }

        // Live hint: after ~3s of recording with nothing detected, flag it.
        setSilentLive(!soundDetectedRef.current && secondsRef.current >= 3);

        levelRafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch (err) {
      console.warn("Audio level monitoring unavailable:", err);
    }
  };

  const stopLevelMonitor = () => {
    if (levelRafRef.current) {
      cancelAnimationFrame(levelRafRef.current);
      levelRafRef.current = null;
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch (_) {}
      audioContextRef.current = null;
    }
    analyserRef.current = null;
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      stopLevelMonitor();
      setRecording(false);
      setSilentLive(false);
    }
  };

  const handleUpload = async () => {
    // ── Silent-recording guard ──────────────────────────────────────────────
    // If the mic never picked up meaningful audio, warn the user before spending
    // time processing an empty recording. They can still proceed if they want.
    if (!soundDetectedRef.current) {
      const proceedAnyway = window.confirm(
        "⚠️ No speech was detected in this recording — the microphone may not have " +
        "picked up any audio.\n\n" +
        "This often means the wrong microphone was selected or the mic was muted.\n\n" +
        "• Click \"Cancel\" to discard this recording and try again.\n" +
        "• Click \"OK\" to process it anyway."
      );
      if (!proceedAnyway) {
        // Discard the silent recording so the user can re-record cleanly.
        audioChunksRef.current = [];
        return;
      }
    }

    setGenerating(true);

    const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });

    // Create a local object URL so TranscriptPage can play the audio back
    if (audioBlobUrlRef.current) URL.revokeObjectURL(audioBlobUrlRef.current);
    audioBlobUrlRef.current = URL.createObjectURL(audioBlob);

    const formData = new FormData();
    formData.append("file", audioBlob, "recording.webm");

    if (sessionDataRef.current) {
      formData.append("doctor_id",  sessionDataRef.current.doctorId);
      formData.append("patient_id", sessionDataRef.current.patientId);
    }

    try {
      const response = await fetch("/api/process", {
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

        onNavigate("Transcript", {
          data:        data.data,
          doctorName:  sessionDataRef.current?.doctorName,
          patientName: sessionDataRef.current?.patientName,
          duration:    `${mm}:${ss}`,
          audioUrl:    audioBlobUrlRef.current,  // ← passed to transcript
        });
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

  const handleModalConfirm = async (formData) => {
    sessionDataRef.current = formData;
    setShowModal(false);
    await startRecording();
  };

  const handleConsentConfirm = () => {
    setShowConsent(false);
    setShowModal(true);
  };

  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 40 }}>

      <RecordingCircle seconds={seconds} />

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {!recording ? (
            <button
              onClick={() => setShowConsent(true)}
              disabled={generating}
              style={{
                padding: "14px 48px", borderRadius: 40, border: "none", cursor: "pointer",
                background: "#2563eb", color: "#fff", fontWeight: 700, fontSize: 16,
                fontFamily: "inherit", transition: "all 0.2s",
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
                background: "#1e40af", color: "#fff", fontWeight: 700, fontSize: 16,
                fontFamily: "inherit", boxShadow: "0 0 0 4px rgba(37,99,235,0.25)",
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
            style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#2563eb", animation: "fadeInUp 0.3s ease" }}
          >
            Processing audio... this may take a moment
          </p>
        )}

        {recording && silentLive && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#fef2f2", border: "1.5px solid #fca5a5", borderRadius: 40,
            padding: "8px 18px", fontSize: 13, fontWeight: 700, color: "#b91c1c",
            animation: "fadeInUp 0.3s ease",
          }}>
            <span style={{ fontSize: 15 }}>🔇</span>
            No sound detected — check your microphone
          </div>
        )}
      </div>

      {showConsent && (
        <ConsentModal
          onConfirm={handleConsentConfirm}
          onCancel={() => setShowConsent(false)}
        />
      )}

      {showModal && (
        <SessionModal
          onConfirm={handleModalConfirm}
          onCancel={() => setShowModal(false)}
          onNavigate={onNavigate}
        />
      )}

      {showHelp && <HelpPopup onClose={() => setShowHelp(false)} />}

      <button
        onClick={() => setShowHelp(true)}
        style={{
          position: "fixed", bottom: 28, right: 28,
          width: 44, height: 44, borderRadius: "50%",
          background: "#2563eb", border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 16px rgba(37,99,235,0.35)",
          color: "#fff", fontSize: 20, fontWeight: 700, zIndex: 50,
        }}
      >
        ?
      </button>
    </div>
  );
}