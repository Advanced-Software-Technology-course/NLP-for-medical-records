import { useState } from "react";

const DOCTOR_TITLES = ["Dr.", "Prof.", "Assoc. Prof."];

const primaryBtn = {
  flex: 2, height: 40, borderRadius: 40, border: "none",
  background: "#2563eb", color: "#fff",
  fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
};
const secondaryBtn = {
  flex: 1, height: 40, borderRadius: 40,
  border: "1px solid #e2e8f0", background: "transparent",
  fontSize: 14, fontWeight: 600, color: "#64748b", cursor: "pointer", fontFamily: "inherit",
};

export default function CreateDoctorPage({ onNavigate }) {
  const [form, setForm] = useState({ title: "", first_name: "", last_name: "" });
  const [errors, setErrors] = useState({});
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const validate = () => {
    const e = {};
    if (!form.first_name.trim()) e.first_name = true;
    if (!form.last_name.trim()) e.last_name = true;
    return e;
  };

  const handleSubmit = async () => {
    const e = validate();
    if (Object.keys(e).length) { setErrors(e); return; }
    setSaving(true);
    try {
      const res = await fetch("http://localhost:5000/api/doctors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (res.ok) {
        setSuccess(true);
        setForm({ title: "", first_name: "", last_name: "" });
      } else {
        const data = await res.json();
        alert(data.error || "Failed to create doctor");
      }
    } catch {
      alert("Network error. Is the backend running?");
    } finally {
      setSaving(false);
    }
  };

  const inputStyle = (key) => ({
    width: "100%", height: 38, padding: "0 12px",
    border: `1px solid ${errors[key] ? "#ef4444" : "#e2e8f0"}`,
    borderRadius: 8, fontSize: 14, fontFamily: "inherit",
    outline: "none", boxSizing: "border-box",
    boxShadow: errors[key] ? "0 0 0 2px rgba(239,68,68,0.15)" : "none",
  });

  const labelStyle = {
    display: "block", fontSize: 13, fontWeight: 600,
    color: "#475569", marginBottom: 6,
  };

  if (success) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 16 }}>
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          background: "#dcfce7", display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 28, color: "#16a34a",
        }}>✓</div>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: "#1e3a8a" }}>Doctor created successfully</h2>
        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          <button onClick={() => setSuccess(false)} style={secondaryBtn}>Add another</button>
          <button onClick={() => onNavigate("Home")} style={primaryBtn}>Back to Home</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, padding: "40px 16px" }}>
      <div style={{ width: "100%", maxWidth: 480 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 800, color: "#1e3a8a" }}>Add Doctor</h2>
        <p style={{ margin: "0 0 28px", color: "#64748b", fontSize: 14 }}>
          Register a new doctor to use in consultations.
        </p>

        <div style={{ marginBottom: 16 }}>
          <label style={labelStyle}>Title</label>
          <select
            style={{ ...inputStyle(), padding: "0 12px", height: 38 }}
            value={form.title}
            onChange={set("title")}
          >
            <option value="">None</option>
            {DOCTOR_TITLES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>
          <div>
            <label style={labelStyle}>
              First name <span style={{ color: "#ef4444" }}>*</span>
            </label>
            <input
              style={inputStyle("first_name")}
              value={form.first_name}
              onChange={set("first_name")}
              onFocus={() => setErrors(e => ({ ...e, first_name: false }))}
              placeholder="Jane"
            />
          </div>
          <div>
            <label style={labelStyle}>
              Last name <span style={{ color: "#ef4444" }}>*</span>
            </label>
            <input
              style={inputStyle("last_name")}
              value={form.last_name}
              onChange={set("last_name")}
              onFocus={() => setErrors(e => ({ ...e, last_name: false }))}
              placeholder="Smith"
            />
          </div>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={() => onNavigate("Home")} style={secondaryBtn}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            style={{ ...primaryBtn, opacity: saving ? 0.6 : 1 }}
          >
            {saving ? "Saving…" : "Create Doctor"}
          </button>
        </div>
      </div>
    </div>
  );
}
