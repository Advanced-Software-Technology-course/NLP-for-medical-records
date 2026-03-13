export default function Waveform({ active }) {
  const bars = Array.from({ length: 48 });
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, height: 36 }}>
      {bars.map((_, i) => {
        const h = active
          ? Math.sin(i * 0.6) * 10 + Math.sin(i * 1.3) * 6 + 14
          : 4 + Math.abs(Math.sin(i * 0.5)) * 10;
        return (
          <div
            key={i}
            style={{
              width: 3,
              borderRadius: 2,
              height: h,
              background: active ? "#2563eb" : "#94a3b8",
              opacity: active ? 0.7 + Math.sin(i) * 0.3 : 0.5,
              transition: "height 0.4s ease",
            }}
          />
        );
      })}
    </div>
  );
}