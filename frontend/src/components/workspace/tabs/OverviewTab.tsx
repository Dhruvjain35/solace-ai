import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { PatientDetailBody } from "../../clinician/PatientDetailBody";
import { usePatientWorkspace } from "../PatientWorkspaceContext";

/**
 * Overview tab — the full clinical record for the workspace patient.
 * Renders the shared `PatientDetailBody` (also used by the dashboard drawer)
 * wired to the workspace context.
 */
export default function OverviewTab() {
  const { hospitalId, patient, loading, error, reloadPatient } = usePatientWorkspace();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
    );
  }

  if (!patient) {
    return <div className="text-text-muted text-sm py-8">No patient record available.</div>;
  }

  return (
    <PatientDetailBody
      detail={patient}
      hospitalId={hospitalId}
      authenticated
      showScribeLink={false}
      onDetailChange={() => reloadPatient()}
      onAfterMarkSeen={() => {
        navigate(`/${hospitalId}/clinician`);
      }}
    />
  );
}
