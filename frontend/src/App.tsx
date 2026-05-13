import { Navigate, Route, Routes } from "react-router-dom";
import PatientIntake from "./pages/PatientIntake";
import PatientResult from "./pages/PatientResult";
import ClinicianDashboard from "./pages/ClinicianDashboard";
import QRCard from "./pages/QRCard";
import VoiceAgent from "./pages/VoiceAgent";
import EHRCallback from "./pages/EHRCallback";
import PatientPrintView from "./pages/PatientPrintView";
import PatientSchedule from "./pages/PatientSchedule";
import WorkflowsAdmin from "./pages/WorkflowsAdmin";
import ClinicianScribe from "./pages/ClinicianScribe";
import ClinicianLetters from "./pages/ClinicianLetters";
import ClinicianInbox from "./pages/ClinicianInbox";
import ClinicianTools from "./pages/ClinicianTools";
import ClinicianOps from "./pages/ClinicianOps";
import PatientDetailPage from "./pages/PatientDetailPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/demo" replace />} />
      <Route path="/voice" element={<VoiceAgent />} />
      <Route path="/ehr/callback" element={<EHRCallback />} />
      <Route path="/:hospitalId" element={<PatientIntake />} />
      <Route path="/:hospitalId/qr" element={<QRCard />} />
      <Route path="/:hospitalId/schedule" element={<PatientSchedule />} />
      <Route path="/:hospitalId/result/:patientId" element={<PatientResult />} />
      <Route path="/:hospitalId/clinician" element={<ClinicianDashboard />} />
      <Route path="/:hospitalId/clinician/print/:patientId" element={<PatientPrintView />} />
      <Route path="/:hospitalId/clinician/workflows" element={<WorkflowsAdmin />} />
      <Route path="/:hospitalId/clinician/scribe" element={<ClinicianScribe />} />
      <Route path="/:hospitalId/clinician/patient/:patientId" element={<PatientDetailPage />} />
      <Route path="/:hospitalId/clinician/patient/:patientId/scribe" element={<ClinicianScribe />} />
      <Route path="/:hospitalId/clinician/letters" element={<ClinicianLetters />} />
      <Route path="/:hospitalId/clinician/inbox" element={<ClinicianInbox />} />
      <Route path="/:hospitalId/clinician/tools" element={<ClinicianTools />} />
      <Route path="/:hospitalId/clinician/ops" element={<ClinicianOps />} />
      <Route path="*" element={<Navigate to="/demo" replace />} />
    </Routes>
  );
}
