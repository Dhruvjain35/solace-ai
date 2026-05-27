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
import ClinicianLanding from "./pages/ClinicianLanding";
import AuthVerify from "./pages/AuthVerify";
import ShowcaseDemo from "./pages/ShowcaseDemo";

// Per-hospital routes. Rendered once under the bare `/:hospitalId` prefix
// (legacy, keeps `/demo` working) and once under `/h/:hospitalId` (provisioned
// hospital workspaces). Both bind the same `:hospitalId` param, so every page
// reads its workspace identically via useParams().
function hospitalRoutes(prefix: string) {
  return [
    <Route key={`${prefix}-intake`} path={`${prefix}/:hospitalId`} element={<PatientIntake />} />,
    <Route key={`${prefix}-verify`} path={`${prefix}/:hospitalId/auth/verify`} element={<AuthVerify />} />,
    <Route key={`${prefix}-qr`} path={`${prefix}/:hospitalId/qr`} element={<QRCard />} />,
    <Route key={`${prefix}-schedule`} path={`${prefix}/:hospitalId/schedule`} element={<PatientSchedule />} />,
    <Route key={`${prefix}-result`} path={`${prefix}/:hospitalId/result/:patientId`} element={<PatientResult />} />,
    <Route key={`${prefix}-clin`} path={`${prefix}/:hospitalId/clinician`} element={<ClinicianDashboard />} />,
    <Route key={`${prefix}-print`} path={`${prefix}/:hospitalId/clinician/print/:patientId`} element={<PatientPrintView />} />,
    <Route key={`${prefix}-wf`} path={`${prefix}/:hospitalId/clinician/workflows`} element={<WorkflowsAdmin />} />,
    <Route key={`${prefix}-scribe`} path={`${prefix}/:hospitalId/clinician/scribe`} element={<ClinicianScribe />} />,
    <Route key={`${prefix}-detail`} path={`${prefix}/:hospitalId/clinician/patient/:patientId`} element={<PatientDetailPage />} />,
    <Route key={`${prefix}-detail-scribe`} path={`${prefix}/:hospitalId/clinician/patient/:patientId/scribe`} element={<ClinicianScribe />} />,
    <Route key={`${prefix}-letters`} path={`${prefix}/:hospitalId/clinician/letters`} element={<ClinicianLetters />} />,
    <Route key={`${prefix}-inbox`} path={`${prefix}/:hospitalId/clinician/inbox`} element={<ClinicianInbox />} />,
    <Route key={`${prefix}-tools`} path={`${prefix}/:hospitalId/clinician/tools`} element={<ClinicianTools />} />,
    <Route key={`${prefix}-ops`} path={`${prefix}/:hospitalId/clinician/ops`} element={<ClinicianOps />} />,
  ];
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/demo" replace />} />
      <Route path="/clinicians" element={<ClinicianLanding />} />
      {/* Standalone split-screen showcase: patient intake + live clinician dashboard. */}
      <Route path="/showcase" element={<ShowcaseDemo />} />
      <Route path="/voice" element={<VoiceAgent />} />
      <Route path="/ehr/callback" element={<EHRCallback />} />
      {hospitalRoutes("")}
      {hospitalRoutes("/h")}
      <Route path="*" element={<Navigate to="/demo" replace />} />
    </Routes>
  );
}
