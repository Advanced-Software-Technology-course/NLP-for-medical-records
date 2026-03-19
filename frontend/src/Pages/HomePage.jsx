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

//help popup
const HELP_STEPS = [
  { title: "Start Recording", desc: 'Tap "Start Recording" to begin capturing the consultation.' },
  { title: "Timer Runs", desc: "The timer tracks the duration of your recording in real time." },
  { title: "Stop & Proceed", desc: "Hit the red stop button to end the session and go to the transcript." },
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


export default function HomePage({ onNavigate, onDurationSave, onDataReceived }) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [showHelp, setShowHelp] = useState(false);
  const [generating, setGenerating] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const secondsRef = useRef(0);

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

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      // We assign onstop here, but handleUpload needs current state.
      // Since handleUpload is a stable function reference (well, in this render), 
      // it might close over old state if not careful.
      // However, to be safe, we'll define the logic inside onstop or 
      // rely on a ref for seconds.
      mediaRecorderRef.current.onstop = () => {
         // Define the upload logic here to ensure it runs when stopped
         handleUpload(); 
      };

      mediaRecorderRef.current.start();
      setRecording(true);
      setSeconds(0);
      secondsRef.current = 0;
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("Could not access microphone. Please ensure you have granted permission.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      // Stop all tracks to release microphone
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      setRecording(false);
    }
  };

  const handleUpload = async () => {
    setGenerating(true);
    
    // Create blob from chunks
    const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' }); 
    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.wav');

    try {
      const response = await fetch('http://localhost:5000/api/process', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        // Save duration using ref to avoid stale closure
        const s = secondsRef.current;
        const mm = String(Math.floor(s / 60)).padStart(2, "0");
        const ss = String(s % 60).padStart(2, "0");
        onDurationSave(`${mm}:${ss}`);
        
        // Save data
        if (onDataReceived) {
          onDataReceived(data.data);
        }
        
        onNavigate("Transcript");
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


  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 40 }}>
      {showHelp && <HelpPopup onClose={() => setShowHelp(false)} />}
      <RecordingCircle seconds={seconds} />

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {!recording ? (
            <button
              onClick={startRecording}
              disabled={generating}
              style={{
                padding: "14px 48px", borderRadius: 40, border: "none", cursor: "pointer",
                background: "#2563eb",
                color: "#fff", fontWeight: 700, fontSize: 16, fontFamily: "inherit",
                transition: "all 0.2s",
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
                background: "#1e40af",
                color: "#fff", fontWeight: 700, fontSize: 16, fontFamily: "inherit",
                boxShadow: "0 0 0 4px rgba(37,99,235,0.25)",
                display: "flex", alignItems: "center", gap: 10
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
            style={{
              margin: 0, fontSize: 14, fontWeight: 600, color: "#2563eb",
              animation: "fadeInUp 0.3s ease",
            }}
          >
            Processing audio... this may take a moment
          </p>
        )}
      </div>

      {/* Help button */}
      <button
        onClick={() => setShowHelp(true)}
        style={{
          position: "fixed", bottom: 28, right: 28,
          width: 44, height: 44, borderRadius: "50%",
          background: "#2563eb", border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 16px rgba(37,99,235,0.35)",
          color: "#fff", fontSize: 20, fontWeight: 700,
          zIndex: 50,
        }}
      >
        ?
      </button>

      {showHelp && <HelpPopup onClose={() => setShowHelp(false)} />}
    </div>
  );
}