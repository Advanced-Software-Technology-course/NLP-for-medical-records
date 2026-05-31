import { useEffect, useState } from "react";

export default function ToastNotification({ message, type = "success", duration = 3000, onClose }) {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false);
      if (onClose) onClose();
    }, duration);

    return () => clearTimeout(timer);
  }, [duration, onClose]);

  const bgColor = type === "success" ? "#10b981" : type === "error" ? "#ef4444" : "#f59e0b";
  const icon = type === "success" ? "✓" : type === "error" ? "✕" : "!";

  return (
    <>
      <style>{`
        @keyframes slideIn {
          from {
            transform: translateX(400px);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes slideOut {
          from {
            transform: translateX(0);
            opacity: 1;
          }
          to {
            transform: translateX(400px);
            opacity: 0;
          }
        }
      `}</style>
      {isVisible && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            zIndex: 1000,
            animation: isVisible ? "slideIn 0.3s ease" : "slideOut 0.3s ease",
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 20px",
            background: bgColor,
            color: "#fff",
            borderRadius: 8,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          <span style={{ fontSize: 18, fontWeight: 700 }}>{icon}</span>
          <span>{message}</span>
        </div>
      )}
    </>
  );
}
