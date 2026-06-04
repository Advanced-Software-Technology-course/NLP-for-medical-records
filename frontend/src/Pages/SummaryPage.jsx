import { useState, useEffect, useRef } from "react";

const API_BASE = "http://localhost:5000";

function parseSoap(data) {
  if (!data) return { subjective: "", objective: "", assessment: "", plan: "" };

  // Already a parsed object (from history)
  if (data.soap && typeof data.soap === "object") return data.soap;

  // Raw SOAP text from backend
  if (data.soap_notes) {
    const s = data.soap_notes;
    return {
      subjective: s.split("**O**")[0]?.replace("**S** - Subjective:", "").trim() ?? "",
      objective:  s.split("**O** - Objective:")[1]?.split("**A**")[0]?.trim() ?? "",
      assessment: s.split("**A** - Assessment:")[1]?.split("**P**")[0]?.trim() ?? "",
      plan:       s.split("**P** - Plan:")[1]?.trim() ?? "",
    };
  }

  return { subjective: "", objective: "", assessment: "", plan: "" };
}

function parseSummary(data) {
  if (!data) return "";
  return data.summary || data.aiSummary || "";
}

// Section labels the summarization model is prompted to produce. Used to add
// a visible break + emphasis before each one so the summary isn't a wall of text.
const SUMMARY_SECTIONS = [
  "Chief Complaint",
  "Key Symptoms",
  "Relevant Medical History",
  "Medical History",
  "Working Diagnosis",
  "Diagnosis",
  "Treatment Plan",
  "Next Steps",
  "Plan",
  "Summary",
  "Assessment",
];

// Render the AI summary with line breaks between sections. We split the text into
// lines, detect lines that begin with a known section label (with or without a
// leading bullet / markdown marker) and render those as bold headings, leaving a
// gap before each. Everything else is preserved as-is with its newlines.
function renderSummary(text) {
  if (!text) return null;

  const lines = text.split(/\r?\n/);

  const blocks = [];
  lines.forEach((rawLine) => {
    const line = rawLine.replace(/\*\*/g, "").trim();
    if (!line) return;

    // Strip a leading bullet marker for label detection.
    const noBullet = line.replace(/^[-•*]\s*/, "");
    const labelMatch = SUMMARY_SECTIONS.find((label) => {
      const re = new RegExp(`^${label}\\s*:`, "i");
      return re.test(noBullet);
    });

    if (labelMatch) {
      const re = new RegExp(`^${labelMatch}\\s*:\\s*`, "i");
      const rest = noBullet.replace(re, "").trim();
      blocks.push({ type: "section", label: labelMatch, body: rest });
    } else {
      blocks.push({ type: "text", body: line });
    }
  });

  if (blocks.length === 0) {
    return <p style={{ color: "#374151", margin: 0, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{text}</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {blocks.map((b, i) =>
        b.type === "section" ? (
          <div key={i}>
            <p style={{ margin: 0, fontWeight: 700, color: "#1e3a8a", fontSize: 14, textTransform: "uppercase", letterSpacing: 0.4 }}>
              {b.label}
            </p>
            {b.body && (
              <p style={{ margin: "4px 0 0", color: "#374151", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                {b.body}
              </p>
            )}
          </div>
        ) : (
          <p key={i} style={{ margin: 0, color: "#374151", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
            {b.body}
          </p>
        )
      )}
    </div>
  );
}

export default function SummaryPage({ onNavigate, doctorName, patientName, duration, data }) {
  const [editing, setEditing]     = useState(false);
  const [aiSummary, setAiSummary] = useState(() => parseSummary(data));
  const [soap, setSoap]           = useState(() => parseSoap(data));
  const [saving, setSaving]       = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [justSaved, setJustSaved] = useState(false);

  // Baseline values representing what is currently persisted. Updated after a
  // successful save so the dirty check compares against the latest saved state.
  const [savedSummary, setSavedSummary] = useState(() => parseSummary(data));
  const [savedSoap, setSavedSoap]       = useState(() => parseSoap(data));

  const consultationId = data?.id ?? null;

  // Re-parse whenever data changes (e.g. navigating from History)
  useEffect(() => {
    const s = parseSummary(data);
    const sp = parseSoap(data);
    setAiSummary(s);
    setSoap(sp);
    setSavedSummary(s);
    setSavedSoap(sp);
    setEditing(false);
    setSaveError(null);
    setJustSaved(false);
    accumulatedRef.current = data?.edit_duration_seconds ?? 0;
    setDisplaySeconds(data?.edit_duration_seconds ?? 0);
  }, [data]);

  // ── Unsaved-changes detection ──────────────────────────────────────────────
  const isDirty =
    editing &&
    (aiSummary !== savedSummary ||
      JSON.stringify(soap) !== JSON.stringify(savedSoap));

  const editStartRef    = useRef(null);
  const accumulatedRef  = useRef(data?.edit_duration_seconds ?? 0);
  const timerIntervalRef = useRef(null);
  const [displaySeconds, setDisplaySeconds] = useState(data?.edit_duration_seconds ?? 0);

  const isDirtyRef = useRef(isDirty);
  useEffect(() => { isDirtyRef.current = isDirty; }, [isDirty]);

  // Warn if the user tries to close/reload the tab with unsaved edits.
  useEffect(() => {
    const handler = (e) => {
      if (isDirtyRef.current) {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  // Guard in-app navigation (e.g. back to Transcript) when there are unsaved edits.
  const guardedNavigate = (...args) => {
    if (
      isDirty &&
      !window.confirm("You have unsaved changes. Leave this note without saving?")
    ) {
      return;
    }
    onNavigate(...args);
  };

  const cols = ["Subjective", "Objective", "Assessment", "Plan"];
  const keys = ["subjective", "objective", "assessment", "plan"];

  const handleSave = async () => {
    setSaveError(null);

    // No backing id (shouldn't normally happen) -> keep edits locally so the user
    // doesn't silently lose them, but surface that they aren't persisted.
    if (!consultationId) {
      setSavedSummary(aiSummary);
      setSavedSoap(soap);
      setEditing(false);
      setSaveError("Saved locally only — this note has no record id, so it can't be stored on the server.");
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/consultations/${consultationId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          summary: aiSummary,
          soap,
          edit_duration_seconds: editStartRef.current
            ? Math.round((Date.now() - editStartRef.current) / 1000)
            : 0,
        }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);

      clearInterval(timerIntervalRef.current);
      accumulatedRef.current = displaySeconds;

      // Commit the new baseline so the dirty check resets.
      setSavedSummary(aiSummary);
      setSavedSoap(soap);
      setEditing(false);
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2500);
    } catch (err) {
      console.error("Failed to save consultation edits:", err);
      setSaveError("Could not save your changes. Please check your connection and try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (
      isDirty &&
      !window.confirm("Discard your unsaved changes to this note?")
    ) {
      return;
    }
    clearInterval(timerIntervalRef.current);
    setDisplaySeconds(accumulatedRef.current);
    setAiSummary(savedSummary);
    setSoap(savedSoap);
    setEditing(false);
    setSaveError(null);
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 70 }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1e3a8a", margin: 0 }}>Consultation Summary</h1>
          <p style={{ color: "#2563eb", fontWeight: 600, margin: "6px 0 0", fontSize: 16 }}>Doctor: {doctorName}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <p style={{ fontWeight: 700, color: "#1e3a8a", margin: 0 }}>Patient: {patientName}</p>
          <p style={{ fontWeight: 700, color: "#1e3a8a", margin: "4px 0 0" }}>Duration: {duration}</p>
        </div>
      </div>

      {/* Unsaved-changes banner */}
      {isDirty && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "#fffbeb", border: "1.5px solid #fcd34d", borderRadius: 10,
          padding: "10px 14px", marginBottom: 20, fontSize: 13, color: "#92400e", fontWeight: 600,
        }}>
          <span style={{ fontSize: 15 }}>⚠️</span>
          You have unsaved changes. Click Save to keep them.
        </div>
      )}

      {/* Saved confirmation */}
      {justSaved && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "#f0fdf4", border: "1.5px solid #86efac", borderRadius: 10,
          padding: "10px 14px", marginBottom: 20, fontSize: 13, color: "#166534", fontWeight: 600,
        }}>
          <span style={{ fontSize: 15 }}>✓</span>
          Changes saved.
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "#fef2f2", border: "1.5px solid #fca5a5", borderRadius: 10,
          padding: "10px 14px", marginBottom: 20, fontSize: 13, color: "#b91c1c", fontWeight: 600,
        }}>
          <span style={{ fontSize: 15 }}>⚠️</span>
          {saveError}
        </div>
      )}

      {/* AI Summary */}
      <div style={{ marginBottom: 46 }}>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: "#1e3a8a", marginBottom: 10 }}>AI Generated Summary</h2>
        {aiSummary || editing ? (
          editing ? (
            <textarea
              value={aiSummary}
              onChange={e => setAiSummary(e.target.value)}
              rows={8}
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "12px 14px", borderRadius: 10, border: "2px solid #2563eb",
                fontSize: 15, color: "#374151", lineHeight: 1.7,
                fontFamily: "inherit", resize: "vertical", outline: "none",
              }}
            />
          ) : (
            renderSummary(aiSummary)
          )
        ) : (
          <p style={{ color: "#94a3b8", fontStyle: "italic", margin: 0 }}>No summary available.</p>
        )}
      </div>

      {/* SOAP Table */}
      <div style={{ marginBottom: 48 }}>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: "#1e3a8a", marginBottom: 16 }}>Structured Clinical Note</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: 10, overflow: "hidden", boxShadow: "0 1px 6px rgba(30,58,138,0.08)" }}>
            <thead>
              <tr style={{ background: "#dbeafe" }}>
                {cols.map(c => (
                  <th key={c} style={{ padding: "12px 16px", textAlign: "left", fontWeight: 700, color: "#1e3a8a", fontSize: 14, borderBottom: "1px solid #bfdbfe" }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {keys.map((key) => (
                  <td key={key} style={{ padding: "14px 16px", color: "#374151", fontSize: 14, borderBottom: "1px solid #e2e8f0", verticalAlign: "top" }}>
                    {editing ? (
                      <textarea
                        value={soap[key] ?? ""}
                        onChange={e => setSoap(prev => ({ ...prev, [key]: e.target.value }))}
                        rows={4}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          padding: "8px 10px", borderRadius: 8, border: "2px solid #2563eb",
                          fontSize: 13, color: "#374151", fontFamily: "inherit",
                          resize: "vertical", outline: "none",
                        }}
                      />
                    ) : (
                      soap[key]
                        ? <span style={{ whiteSpace: "pre-wrap" }}>{soap[key]}</span>
                        : <span style={{ color: "#94a3b8", fontStyle: "italic" }}>—</span>
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          onClick={() => guardedNavigate("Transcript")}
          style={{ background: "none", border: "none", cursor: "pointer", color: "#2563eb", fontWeight: 700, fontSize: 15, display: "flex", alignItems: "center", gap: 6 }}
        >
          ← View transcript
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {editing && (
            <span style={{ fontSize: 13, fontWeight: 600, color: "#64748b", fontFamily: "'DM Mono', monospace" }}>
              {String(Math.floor(displaySeconds / 60)).padStart(2, "0")}:{String(displaySeconds % 60).padStart(2, "0")}
            </span>
          )}
          {editing && (
            <button
              onClick={handleCancel}
              disabled={saving}
              style={{ padding: "12px 28px", borderRadius: 40, border: "2px solid #e2e8f0", background: "#fff", color: "#64748b", fontWeight: 700, fontSize: 15, cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.6 : 1 }}
            >
              Cancel
            </button>
          )}
          <button
            onClick={editing ? handleSave : () => {
              setJustSaved(false);
              editStartRef.current = Date.now();
              setEditing(true);
              timerIntervalRef.current = setInterval(() => {
                setDisplaySeconds(accumulatedRef.current + Math.round((Date.now() - editStartRef.current) / 1000));
              }, 1000);
            }}
            disabled={saving}
            style={{
              padding: "12px 28px", borderRadius: 40,
              border: editing ? "none" : "2px solid #1e3a8a",
              background: editing ? (saving ? "#93c5fd" : "#2563eb") : "#fff",
              color: editing ? "#fff" : "#1e3a8a",
              fontWeight: 700, fontSize: 15, cursor: saving ? "not-allowed" : "pointer",
              display: "flex", alignItems: "center", gap: 8, transition: "all 0.2s",
            }}
          >
            {editing ? (saving ? "Saving…" : "Save") : "Edit ✏️"}
          </button>
        </div>
      </div>
    </div>
  );
}