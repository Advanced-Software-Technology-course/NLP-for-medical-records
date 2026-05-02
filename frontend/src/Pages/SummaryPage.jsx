import { useState, useEffect } from "react";

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

export default function SummaryPage({ onNavigate, doctorName, patientName, duration, data }) {
  const [editing, setEditing]     = useState(false);
  const [aiSummary, setAiSummary] = useState(() => parseSummary(data));
  const [soap, setSoap]           = useState(() => parseSoap(data));

  // Re-parse whenever data changes (e.g. navigating from History)
  useEffect(() => {
    setAiSummary(parseSummary(data));
    setSoap(parseSoap(data));
    setEditing(false);
  }, [data]);

  const originalSummary = parseSummary(data);
  const originalSoap    = parseSoap(data);

  const cols = ["Subjective", "Objective", "Assessment", "Plan"];
  const keys = ["subjective", "objective", "assessment", "plan"];

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

      {/* AI Summary */}
      <div style={{ marginBottom: 46 }}>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: "#1e3a8a", marginBottom: 10 }}>AI Generated Summary</h2>
        {aiSummary ? (
          editing ? (
            <textarea
              value={aiSummary}
              onChange={e => setAiSummary(e.target.value)}
              rows={3}
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "12px 14px", borderRadius: 10, border: "2px solid #2563eb",
                fontSize: 15, color: "#374151", lineHeight: 1.7,
                fontFamily: "inherit", resize: "vertical", outline: "none",
              }}
            />
          ) : (
            <p style={{ color: "#374151", margin: 0, lineHeight: 1.7 }}>{aiSummary}</p>
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
                        rows={3}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          padding: "8px 10px", borderRadius: 8, border: "2px solid #2563eb",
                          fontSize: 13, color: "#374151", fontFamily: "inherit",
                          resize: "vertical", outline: "none",
                        }}
                      />
                    ) : (
                      soap[key] || <span style={{ color: "#94a3b8", fontStyle: "italic" }}>—</span>
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
          onClick={() => onNavigate("Transcript")}
          style={{ background: "none", border: "none", cursor: "pointer", color: "#2563eb", fontWeight: 700, fontSize: 15, display: "flex", alignItems: "center", gap: 6 }}
        >
          ← View transcript
        </button>
        <div style={{ display: "flex", gap: 12 }}>
          {editing && (
            <button
              onClick={() => { setAiSummary(originalSummary); setSoap(originalSoap); setEditing(false); }}
              style={{ padding: "12px 28px", borderRadius: 40, border: "2px solid #e2e8f0", background: "#fff", color: "#64748b", fontWeight: 700, fontSize: 15, cursor: "pointer" }}
            >
              Cancel
            </button>
          )}
          <button
            onClick={editing ? () => setEditing(false) : () => setEditing(true)}
            style={{
              padding: "12px 28px", borderRadius: 40,
              border: editing ? "none" : "2px solid #1e3a8a",
              background: editing ? "#2563eb" : "#fff",
              color: editing ? "#fff" : "#1e3a8a",
              fontWeight: 700, fontSize: 15, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 8, transition: "all 0.2s",
            }}
          >
            {editing ? "Save" : "Edit ✏️"}
          </button>
        </div>
      </div>
    </div>
  );
}