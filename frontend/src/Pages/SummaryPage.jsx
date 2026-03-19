import { useState, useEffect } from "react";

const MOCK_SUMMARY = {
  aiSummary: "Patient reports chest pain starting yesterday and the pain worsens during physical activity.",
  soap: {
    subjective: "Patient reports chest pain since yesterday",
    objective: "No respiratory distress observed",
    assessment: "Possible cardiac issue",
    plan: "Recommend ECG and blood test",
  },
};

export default function SummaryPage({ onNavigate, doctorName, patientName, duration, data }) {
  const [editing, setEditing] = useState(false);
  const [aiSummary, setAiSummary] = useState(MOCK_SUMMARY.aiSummary);
  const [soap, setSoap] = useState(MOCK_SUMMARY.soap);

  useEffect(() => {
    if (data) {
      if (data.aiSummary) setAiSummary(data.aiSummary);
      if (data.soap) setSoap(data.soap);
    }
  }, [data]);

  const cols = ["Subjective", "Objective", "Assessment", "Plan"];
  const keys = ["subjective", "objective", "assessment", "plan"];

  const handleSave = () => setEditing(false);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>
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

      
      <div style={{ marginBottom: 46 }}>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: "#1e3a8a", marginBottom: 10 }}>AI Generated Summary</h2>
        {editing ? (
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
                {keys.map((key, i) => (
                  <td key={i} style={{ padding: "14px 16px", color: "#374151", fontSize: 14, borderBottom: "1px solid #e2e8f0", verticalAlign: "top" }}>
                    {editing ? (
                      <textarea
                        value={soap[key]}
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
                      soap[key]
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      
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
              onClick={() => { setSoap(MOCK_SUMMARY.soap); setAiSummary(MOCK_SUMMARY.aiSummary); setEditing(false); }}
              style={{
                padding: "12px 28px", borderRadius: 40, border: "2px solid #e2e8f0",
                background: "#fff", color: "#64748b", fontWeight: 700, fontSize: 15,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
          )}
          <button
            onClick={editing ? handleSave : () => setEditing(true)}
            style={{
              padding: "12px 28px", borderRadius: 40,
              border: editing ? "none" : "2px solid #1e3a8a",
              background: editing ? "#2563eb" : "#fff",
              color: editing ? "#fff" : "#1e3a8a",
              fontWeight: 700, fontSize: 15,
              cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
              transition: "all 0.2s",
            }}
          >
            {editing ? "Save" : "Edit ✏️"}
          </button>
        </div>
      </div>
    </div>
  );
}