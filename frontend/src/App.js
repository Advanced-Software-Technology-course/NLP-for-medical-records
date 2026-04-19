import { useState } from 'react';
import Navbar from './Comp/Navbar';
import HomePage from './Pages/HomePage';
import TranscriptPage from './Pages/TranscriptPage';
import SummaryPage from './Pages/SummaryPage';
import SettingsPage from './Pages/SettingPage';
import HistoryPage from './Pages/HistoryPage';

const DOCTOR_NAME = 'Dr. Smith';
const PATIENT_NAME = 'John Doe';

export default function App() {
  const [active, setActive] = useState('Home');
  const [duration, setDuration] = useState('00:00');
  const [consultationData, setConsultationData] = useState(null);

  const handleLoadConsultation = (c) => {
    setConsultationData(c);
    setDuration(c.duration ?? '—');
    setActive('Summary');
  };

  const renderPage = () => {
    switch (active) {
      case 'Home':
        return (
          <HomePage
            onNavigate={setActive}
            onDurationSave={setDuration}
            onDataReceived={setConsultationData}
          />
        );
      case 'Transcript':
        return (
          <TranscriptPage
            onNavigate={setActive}
            doctorName={DOCTOR_NAME}
            patientName={PATIENT_NAME}
            duration={duration}
            data={consultationData}
          />
        );
      case 'Summary':
        return (
          <SummaryPage
            onNavigate={setActive}
            doctorName={DOCTOR_NAME}
            patientName={PATIENT_NAME}
            duration={duration}
            data={consultationData}
          />
        );
      case 'History':
        return (
          <HistoryPage
            onNavigate={setActive}
            onLoadConsultation={handleLoadConsultation}
          />
        );
      default:
        return <SettingsPage />;
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
        fontFamily: "'Google Sans', sans-serif",
      }}
    >
      <Navbar active={active} onNavigate={setActive} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {renderPage()}
      </main>
    </div>
  );
}