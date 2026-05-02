import { Navigate, Route, Routes } from "react-router-dom";
import PatientIntake from "./pages/PatientIntake";
import PatientResult from "./pages/PatientResult";
import ClinicianDashboard from "./pages/ClinicianDashboard";
import QRCard from "./pages/QRCard";
import VoiceAgent from "./pages/VoiceAgent";
import EHRCallback from "./pages/EHRCallback";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/demo" replace />} />
      <Route path="/voice" element={<VoiceAgent />} />
      <Route path="/ehr/callback" element={<EHRCallback />} />
      <Route path="/:hospitalId" element={<PatientIntake />} />
      <Route path="/:hospitalId/qr" element={<QRCard />} />
      <Route path="/:hospitalId/result/:patientId" element={<PatientResult />} />
      <Route path="/:hospitalId/clinician" element={<ClinicianDashboard />} />
      <Route path="*" element={<Navigate to="/demo" replace />} />
    </Routes>
  );
}
