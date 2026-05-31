import { useState } from 'react';
import Navbar from './Comp/Navbar';
import HomePage from './Pages/HomePage';
import TranscriptPage from './Pages/TranscriptPage';
import SummaryPage from './Pages/SummaryPage';
import SettingsPage from './Pages/SettingPage';
import HistoryPage from './Pages/HistoryPage';
import CreateDoctorPage from './Pages/CreateDoctorPage';
import CreatePatientPage from './Pages/CreatePatientPage';

export default function App() {
  const [active, setActive] = useState('Home');
  const [duration, setDuration] = useState('00:00');
  const [consultationData, setConsultationData] = useState(null);
  const [sessionData, setSessionData] = useState({ doctorName: '', patientName: '' });
  const [audioUrl, setAudioUrl] = useState(null);

  const handleNavigate = (page, props) => {
    if (props?.doctorName || props?.patientName) {
      setSessionData({ doctorName: props.doctorName, patientName: props.patientName });
    }
    if (props?.data) setConsultationData(props.data);
    if (props?.duration) setDuration(props.duration);
    if (props?.audioUrl) setAudioUrl(props.audioUrl);
    setActive(page);
  };

  const handleLoadConsultation = (c) => {
    setConsultationData(c);
    setDuration(c.duration ?? '—');
    setSessionData({
      doctorName:  c.doctorName  ?? c.doctor_name  ?? '',
      patientName: c.patientName ?? c.patient_name ?? '',
    });
    setActive('Summary');
  };

  const renderPage = () => {
    switch (active) {
      case 'Home':
        return (
          <HomePage
            onNavigate={handleNavigate}
            onDurationSave={setDuration}
            onDataReceived={setConsultationData}
          />
        );
      case 'Transcript':
        return (
          <TranscriptPage
            onNavigate={handleNavigate}
            doctorName={sessionData.doctorName}
            patientName={sessionData.patientName}
            duration={duration}
            data={consultationData}
            audioUrl={audioUrl}
          />
        );
      case 'Summary':
        return (
          <SummaryPage
            onNavigate={handleNavigate}
            doctorName={sessionData.doctorName}
            patientName={sessionData.patientName}
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
      case 'Doctors':
        return <CreateDoctorPage onNavigate={setActive} />;
      case 'Patients':
        return <CreatePatientPage onNavigate={setActive} />;
      default:
        return <SettingsPage />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', fontFamily: "'Google Sans', sans-serif" }}>
      <Navbar active={active} onNavigate={setActive} />
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {renderPage()}
      </main>
    </div>
  );
}
