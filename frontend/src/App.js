import { useState } from "react";
import Navbar from "./Comp/Navbar";
import HomePage from "./Pages/HomePage";
import TranscriptPage from "./Pages/TranscriptPage";
import SummaryPage from "./Pages/SummaryPage";
import SettingsPage from "./Pages/SettingPage";

const DOCTOR_NAME = "Dr. Smith";
const PATIENT_NAME = "John Doe";

export default function App() {
  const [active, setActive] = useState("Home");
  const [duration, setDuration] = useState("00:00");

  const renderPage = () => {
    switch (active) {
      case "Home":
        return <HomePage onNavigate={setActive} onDurationSave={setDuration} />;
      case "Transcript":
        return <TranscriptPage onNavigate={setActive} doctorName={DOCTOR_NAME} patientName={PATIENT_NAME} duration={duration} />;
      case "Summary":
        return <SummaryPage onNavigate={setActive} doctorName={DOCTOR_NAME} patientName={PATIENT_NAME} duration={duration} />;
      default:
        return <SettingsPage />;
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh", fontFamily: "'Google Sans', sans-serif" }}>
      <Navbar active={active} onNavigate={setActive} />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {renderPage()}
      </main>
    </div>
  );
}