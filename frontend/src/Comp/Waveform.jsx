import { useEffect, useState } from "react";

export default function Waveform({ active, duration = 30, currentTime = 0 }) {
 
  const totalBars = 48;
  const [heights, setHeights] = useState(Array.from({ length: totalBars }).map(() => 4));

  useEffect(() => {
    if (!active) return;

    const interval = setInterval(() => {
      setHeights(prev =>
        prev.map((h, i) => {
        
          return Math.sin(i * 0.6 + Date.now() / 300) * 10 +
                 Math.sin(i * 1.3 + Date.now() / 500) * 6 + 14;
        })
      );
    }, 50); // update 20 times per second

    return () => clearInterval(interval);
  }, [active]);


  const activeBars = Math.floor((currentTime / duration) * totalBars);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, height: 36 }}>
      {heights.map((h, i) => (
        <div
          key={i}
          style={{
            width: 3,
            borderRadius: 2,
            height: h,
            background: i <= activeBars ? "#2563eb" : "#94a3b8",
            opacity: i <= activeBars ? 0.7 : 0.4,
            transition: "height 0.05s linear, background 0.2s",
          }}
        />
      ))}
    </div>
  );
}