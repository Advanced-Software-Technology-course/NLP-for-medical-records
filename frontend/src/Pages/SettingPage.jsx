import { useState, useEffect, useRef } from "react";

const PRIVACY_PARAGRAPHS = [
  "This system records and processes doctor–patient consultations to assist with clinical documentation. Audio recordings and generated transcripts are stored locally within the clinic's infrastructure to maintain control over patient data.",
  "To perform advanced AI processing such as summarization, the system securely uploads the necessary data to a processing server through encrypted communication. This step allows the system to generate summaries and structured medical notes while maintaining strong data protection standards.",
  "Recorded audio and transcripts are used only for generating consultation transcripts and summaries that help doctors create accurate medical records. Access to this information should be limited to authorized healthcare professionals involved in the patient's care.",
  "Patients should be informed if a consultation is being recorded. The purpose of recording is to improve documentation accuracy and reduce the administrative workload for doctors, allowing them to focus more on patient interaction.",
  "Healthcare providers are responsible for handling all recorded data in accordance with medical privacy regulations and institutional data protection policies.",
];

const BAR_COUNT = 40;


function LiveWaveform({ active, deviceId }) {
  const barsRef = useRef([]);
  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const frameRef = useRef(null);
  const timeRef = useRef(0);

  useEffect(() => {
    cancelAnimationFrame(frameRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close();
    }

    if (!active) {
      const idleLoop = () => {
        timeRef.current += 0.04;
        barsRef.current.forEach((bar, i) => {
          if (!bar) return;
          const h = 4 + Math.abs(Math.sin(i * 0.45 + timeRef.current)) * 10;
          bar.style.height = `${h}px`;
          bar.style.background = "#94a3b8";
          bar.style.opacity = "0.45";
        });
        frameRef.current = requestAnimationFrame(idleLoop);
      };
      frameRef.current = requestAnimationFrame(idleLoop);
      return () => cancelAnimationFrame(frameRef.current);
    }

    //use the selected deviceId if available
    const constraints = {
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    };

    const start = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        streamRef.current = stream;

        const audioCtx = new AudioContext();
        audioCtxRef.current = audioCtx;

        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 128;

        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        const draw = () => {
          analyser.getByteFrequencyData(dataArray);
          barsRef.current.forEach((bar, i) => {
            if (!bar) return;
            const dataIndex = Math.floor((i / BAR_COUNT) * dataArray.length);
            const value = dataArray[dataIndex];
            const h = 4 + (value / 255) * 26;
            bar.style.height = `${h}px`;
            bar.style.background = "#2563eb";
            bar.style.opacity = String(0.4 + (value / 255) * 0.6);
          });
          frameRef.current = requestAnimationFrame(draw);
        };

        draw();
      } catch (err) {
        console.error("Mic access denied:", err);
      }
    };

    start();

    return () => {
      cancelAnimationFrame(frameRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        audioCtxRef.current.close();
      }
    };
  }, [active, deviceId]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, height: 32 }}>
      {Array.from({ length: BAR_COUNT }).map((_, i) => (
        <div
          key={i}
          ref={el => (barsRef.current[i] = el)}
          style={{
            width: 3,
            borderRadius: 2,
            height: "8px",
            background: "#94a3b8",
            opacity: 0.45,
          }}
        />
      ))}
    </div>
  );
}


export default function SettingsPage() {
  const [microphones, setMicrophones] = useState([]);
  const [selectedMic, setSelectedMic] = useState("");
  const [testing, setTesting] = useState(false);
  const [permissionError, setPermissionError] = useState(false);
  const timerRef = useRef(null);

  // load real devices
  useEffect(() => {
    const getMics = async () => {
      try {
        // Request permission first so labels are visible
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const mics = devices.filter(d => d.kind === "audioinput");
        setMicrophones(mics);
        if (mics.length > 0) setSelectedMic(mics[0].deviceId);
      } catch (err) {
        console.error("Could not enumerate devices:", err);
        setPermissionError(true);
      }
    };
    getMics();
  }, []);

  const handleMicTest = () => {
    if (testing) {
      setTesting(false);
      clearTimeout(timerRef.current);
    } else {
      setTesting(true);
      timerRef.current = setTimeout(() => setTesting(false), 5000);
    }
  };

  useEffect(() => () => clearTimeout(timerRef.current), []);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px", width: "100%" }}>
      <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1e3a8a", marginBottom: 36 }}>Settings</h1>

      {/* Microphone section */}
      <div style={{ marginBottom: 52 }}>
        <h2 style={{ fontSize: 17, fontWeight: 800, color: "#1e3a8a", marginBottom: 16 }}>Microphone</h2>

        {permissionError ? (
          <p style={{ color: "#ef4444", fontSize: 14, fontWeight: 600 }}>
            Microphone access was denied. Please allow mic permissions in your browser settings.
          </p>
        ) : (
          <>
            <div style={{ position: "relative", display: "inline-block", marginBottom: 20 }}>
              <select
                value={selectedMic}
                onChange={e => { setSelectedMic(e.target.value); setTesting(false); }}
                style={{
                  appearance: "none",
                  padding: "10px 40px 10px 14px",
                  borderRadius: 6,
                  border: "1.5px solid #cbd5e1",
                  background: "#fff",
                  color: "#1e3a8a",
                  fontSize: 15,
                  fontFamily: "inherit",
                  fontWeight: 500,
                  cursor: "pointer",
                  minWidth: 260,
                  outline: "none",
                }}
              >
                {microphones.length === 0 ? (
                  <option>Loading devices…</option>
                ) : (
                  microphones.map(mic => (
                    <option key={mic.deviceId} value={mic.deviceId}>
                      {mic.label || "Microphone"}
                    </option>
                  ))
                )}
              </select>
              <div style={{
                position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)",
                pointerEvents: "none", color: "#64748b",
              }}>▾</div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
              <button
                onClick={handleMicTest}
                disabled={microphones.length === 0}
                style={{
                  padding: "10px 22px", borderRadius: 6, border: "none", cursor: "pointer",
                  background: testing ? "#ef4444" : "#1e3a8a",
                  color: "#fff", fontWeight: 700, fontSize: 14,
                  fontFamily: "inherit", flexShrink: 0,
                  transition: "background 0.2s",
                  opacity: microphones.length === 0 ? 0.5 : 1,
                }}
              >
                {testing ? "Stop Test" : "Mic Test"}
              </button>
              <LiveWaveform active={testing} deviceId={selectedMic} />
            </div>

            {testing && (
              <p style={{ margin: "10px 0 0", fontSize: 13, color: "#2563eb", fontWeight: 600 }}>
                Listening — speak to test your microphone
              </p>
            )}
          </>
        )}
      </div>

     
      <div style={{ height: 1, background: "#e2e8f0", marginBottom: 36 }} />

     
      <div>
        <h2 style={{ fontSize: 17, fontWeight: 800, color: "#1e3a8a", marginBottom: 20 }}>Privacy Policy</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {PRIVACY_PARAGRAPHS.map((para, i) => (
            <p key={i} style={{ margin: 0, color: "#374151", lineHeight: 1.75, fontSize: 15 }}>
              {para}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}