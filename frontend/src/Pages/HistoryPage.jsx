import { useState, useEffect } from "react";

// ── MOCK MODE ─────────────────────────────────────────────────────────────────
// Set to false when backend is ready
const USE_MOCK = false;

const MOCK_HISTORY = [
  {
    id: 1,
    date: "2025-03-20",
    time: "09:15",
    doctorName: "Dr. Smith",
    patientName: "John Doe",
    duration: "12:34",
    summary: "Patient reports chest pain since yesterday that worsens during physical activity. ECG and blood test recommended. Follow-up in one week.",
  },
  {
    id: 2,
    date: "2025-03-18",
    time: "11:40",
    doctorName: "Dr. Smith",
    patientName: "Jane Doe",
    duration: "08:12",
    summary: "Follow-up on blood pressure medication. Patient reports dizziness in the mornings. Dosage adjusted, monitor for two weeks.",
  },
  {
    id: 3,
    date: "2025-03-15",
    time: "14:00",
    doctorName: "Dr. Smith",
    patientName: "Alice Brown",
    duration: "15:02",
    summary: "Annual checkup. All vitals normal. No significant findings. Patient advised to maintain current lifestyle and diet.",
  },
];
// ─────────────────────────────────────────────────────────────────────────────

export default function HistoryPage({ onNavigate, onLoadConsultation }) {
  const [consultations, setConsultations] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      if (USE_MOCK) {
        await new Promise(res => setTimeout(res, 600));
        setConsultations(MOCK_HISTORY);
        setLoading(false);
        return;
      }
      try {
        const response = await fetch("http://localhost:5000/api/history");
        if (!response.ok) throw new Error("API_ERROR");
        const data = await response.json();
        const mapped = data.map((c) => ({
  id: c.id,
  summary:     c.ai_summary   || c.aiSummary   || c.summary   || "No summary available.",
  transcript:  c.transcript,
  soap:        c.soap,
  date:        c.created_at ? c.created_at.split("T")[0] : "—",
  time:        c.created_at ? c.created_at.split("T")[1]?.slice(0, 5) : "—",
  patientName: c.patient_name || c.patientName || "Unknown Patient",
  doctorName:  c.doctor_name  || c.doctorName  || "Unknown Doctor",
  duration:    c.duration     || "—",
}));
        setConsultations(mapped);
        console.log("First record from backend:", data[0]);
      } catch (err) {
        console.warn("Could not load history from backend:", err);
        setConsultations(MOCK_HISTORY);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, []);

  const previewSummary = (text) => {
    if (!text) return "No summary available.";
    return text.length > 160 ? text.slice(0, 160).trimEnd() + "…" : text;
  };

  const cardStyle = {
    background: "#fff",
    border: "0.5px solid #e2e8f0",
    borderRadius: 14,
    padding: "20px 28px",
    cursor: "pointer",
    marginBottom: 12,
    transition: "border-color 0.15s",
  };

  return (
    <div style={{ width: "80%", margin: "0 auto", padding: "40px 32px" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 32 }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, color: "#1e3a8a", margin: 0 }}>
          Past consultations
        </h1>
        {!loading && consultations.length > 0 && (
          <span style={{ fontSize: 13, color: "#64748b" }}>
            {consultations.length} consultation{consultations.length !== 1 ? "s" : ""} found
          </span>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#64748b", fontSize: 14 }}>
          <div style={{
            width: 16, height: 16, borderRadius: "50%",
            border: "2px solid #e2e8f0", borderTopColor: "#2563eb",
            animation: "spin 0.8s linear infinite",
          }} />
          Loading history...
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* Empty */}
      {!loading && consultations.length === 0 && (
        <div style={{ textAlign: "center", padding: "60px 24px", color: "#94a3b8" }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🗂️</div>
          <p style={{ margin: 0, fontWeight: 500, fontSize: 15 }}>No past consultations yet</p>
          <p style={{ margin: "6px 0 0", fontSize: 13 }}>Consultations will appear here after they are processed.</p>
        </div>
      )}

      {/* Cards */}
      <div>
        {consultations.map((c) => (
          <div
            key={c.id}
            onClick={() => onLoadConsultation?.(c)}
            style={cardStyle}
            onMouseEnter={e => e.currentTarget.style.borderColor = "#cbd5e1"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "#e2e8f0"}
          >
            {/* Top row */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: "50%",
                  background: "#dbeafe", color: "#1d4ed8",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 500, fontSize: 14, flexShrink: 0,
                }}>
                  {(c.patientName ?? "?")[0]}
                </div>
                <div>
                  <p style={{ margin: 0, fontWeight: 500, fontSize: 15, color: "#0f172a" }}>
                    {c.patientName ?? "Unknown Patient"}
                  </p>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>
                    {c.doctorName ?? "Unknown Doctor"}
                  </p>
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <p style={{ margin: 0, fontSize: 13, color: "#64748b" }}>
                  {c.date ?? "—"}{c.time ? ` · ${c.time}` : ""}
                </p>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "#94a3b8" }}>
                  {c.duration ?? "—"}
                </p>
              </div>
            </div>

            {/* Divider */}
            <div style={{ height: "0.5px", background: "#f1f5f9", marginBottom: 12 }} />

            {/* Summary */}
            <p style={{ margin: 0, fontSize: 13, color: "#64748b", lineHeight: 1.65 }}>
              {previewSummary(c.summary)}
            </p>

            {/* Footer */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
              <span style={{ fontSize: 12, color: "#2563eb", fontWeight: 500 }}>
                View full consultation →
              </span>
              <span style={{
                fontSize: 11, padding: "3px 10px", borderRadius: 6,
                background: "#f0fdf4", color: "#16a34a",
              }}>
                Complete
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}