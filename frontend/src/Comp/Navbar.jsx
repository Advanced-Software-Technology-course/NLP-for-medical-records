const NAV_ITEMS = ["Home", "Transcript", "Summary", "History", "Doctors", "Patients", "Settings"];

export default function Navbar({ active, onNavigate }) {
  return (
    <nav style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "16px 40px", background: "#fff",
      marginBottom: "25px",
      borderBottom: "1px solid #e2e8f0",
      position: "sticky", top: 0, zIndex: 100,
    }}>
      {/* Logo placeholder */}
      <div style={{ width: 52, height: 36, position: "relative", opacity: 0.5 }}>
        <div style={{ position: "absolute", inset: 0, border: "2px solid #94a3b8" }} />
        <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: 2, background: "#94a3b8", transform: "translateY(-50%) rotate(20deg)" }} />
        <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: 2, background: "#94a3b8", transform: "translateY(-50%) rotate(-20deg)" }} />
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        {NAV_ITEMS.map(item => (
          <button
            key={item}
            onClick={() => onNavigate(item)}
            style={{
              padding: "8px 18px", background: "none", border: "none", cursor: "pointer",
              fontFamily: "inherit", fontSize: 15, fontWeight: 600,
              color: active === item ? "#1e3a8a" : "#64748b",
              borderBottom: active === item ? "2.5px solid #1e3a8a" : "2.5px solid transparent",
              transition: "all 0.15s",
            }}
          >
            {item}
          </button>
        ))}
      </div>

      <button style={{
        padding: "10px 22px", borderRadius: 40, border: "2px solid #1e3a8a",
        background: "none", color: "#1e3a8a", fontWeight: 700, fontSize: 14,
        cursor: "pointer", fontFamily: "inherit",
      }}>
        Contact us
      </button>
    </nav>
  );
}