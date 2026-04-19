import { Chip } from "../ui/Chip";
import type { MedicalInfo, Sex } from "../../types";

type Props = {
  value: MedicalInfo;
  onChange: (next: MedicalInfo) => void;
};

const ALLERGY_OPTIONS = ["None", "Penicillin", "Sulfa", "Aspirin", "NSAIDs", "Latex", "Peanuts", "Shellfish"];
const MEDICATION_OPTIONS = [
  "None",
  "Blood thinners",
  "Insulin",
  "BP meds",
  "Heart meds",
  "Birth control",
  "SSRIs",
  "Pain meds",
  "Steroids",
];
const CONDITION_OPTIONS = [
  "None",
  "Diabetes",
  "Hypertension",
  "Heart disease",
  "Heart failure",
  "Asthma",
  "COPD",
  "Kidney disease",
  "Cancer",
  "Stroke (prior)",
  "Epilepsy",
  "Depression/Anxiety",
];

const BLOOD_THINNERS = ["Warfarin", "Apixaban (Eliquis)", "Rivaroxaban (Xarelto)", "Dabigatran (Pradaxa)", "Aspirin", "Other"];

const SEVERITY_ORDER: Array<"mild" | "moderate" | "anaphylaxis"> = ["mild", "moderate", "anaphylaxis"];

export function MedicalInfoForm({ value, onChange }: Props) {
  const toggle = (key: "allergies" | "medications" | "conditions", item: string) => {
    const list = value[key];
    let next: string[];
    if (item === "None") {
      next = list.includes("None") ? [] : ["None"];
    } else {
      const without = list.filter((x) => x !== "None" && x !== item);
      next = list.includes(item) ? without : [...without, item];
    }
    const patch: Partial<MedicalInfo> = { [key]: next };

    // Cascade: clearing a condition clears its follow-up data
    if (key === "conditions") {
      if (!next.includes("Diabetes")) patch.diabetes_type = null;
      if (!next.includes("Heart failure")) patch.heart_failure_class = null;
    }
    if (key === "medications" && !next.includes("Blood thinners")) {
      patch.blood_thinner_name = null;
    }
    if (key === "allergies") {
      // Drop severity entries for deselected allergies
      const sev: MedicalInfo["allergy_severity"] = {};
      for (const a of next) {
        if (a !== "None" && value.allergy_severity[a]) sev[a] = value.allergy_severity[a];
      }
      patch.allergy_severity = sev;
    }
    onChange({ ...value, ...patch });
  };

  const setSeverity = (allergy: string, sev: "mild" | "moderate" | "anaphylaxis") => {
    onChange({
      ...value,
      allergy_severity: { ...value.allergy_severity, [allergy]: sev },
    });
  };

  const age = value.age ?? 0;
  const showPregnancy = value.sex === "female" && age >= 12 && age <= 55;
  const showGestational = value.pregnant === true;
  const hasDiabetes = value.conditions.includes("Diabetes");
  const hasHeartFailure = value.conditions.includes("Heart failure");
  const onBloodThinner = value.medications.includes("Blood thinners");
  const nonNoneAllergies = value.allergies.filter((a) => a !== "None");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <label className="text-sm font-semibold block mb-2" htmlFor="age">
          Age
        </label>
        <input
          id="age"
          type="number"
          inputMode="numeric"
          min={0}
          max={120}
          value={value.age ?? ""}
          onChange={(e) => onChange({ ...value, age: e.target.value ? Number(e.target.value) : null })}
          placeholder="38"
          className="w-full h-12 px-4 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-lg outline-none transition-all"
        />
      </div>

      <div>
        <div className="text-sm font-semibold mb-2">Sex</div>
        <div className="flex gap-2">
          {(["male", "female", "other"] as Sex[]).map((s) => (
            <Chip
              key={s}
              label={s[0].toUpperCase() + s.slice(1)}
              selected={value.sex === s}
              onToggle={() =>
                onChange({
                  ...value,
                  sex: s,
                  pregnant: s === "female" ? value.pregnant : null,
                  gestational_weeks: s === "female" ? value.gestational_weeks : null,
                })
              }
            />
          ))}
        </div>
      </div>

      {showPregnancy && (
        <div>
          <div className="text-sm font-semibold mb-2">Pregnant?</div>
          <div className="flex gap-2">
            <Chip label="Yes" selected={value.pregnant === true} onToggle={() => onChange({ ...value, pregnant: true })} />
            <Chip
              label="No"
              selected={value.pregnant === false}
              onToggle={() => onChange({ ...value, pregnant: false, gestational_weeks: null })}
            />
          </div>
        </div>
      )}

      {showGestational && (
        <div className="border-l-2 border-primary-fixed pl-4">
          <label className="text-sm font-semibold block mb-2" htmlFor="gest">
            Weeks pregnant (approximate)
          </label>
          <input
            id="gest"
            type="number"
            inputMode="numeric"
            min={1}
            max={42}
            value={value.gestational_weeks ?? ""}
            onChange={(e) =>
              onChange({ ...value, gestational_weeks: e.target.value ? Number(e.target.value) : null })
            }
            placeholder="24"
            className="w-32 h-11 px-3 rounded-md bg-surface-lowest shadow-soft ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none transition-all"
          />
        </div>
      )}

      {/* Allergies + per-allergy severity follow-up */}
      <div>
        <div className="text-sm font-semibold mb-2">Allergies</div>
        <div className="flex flex-wrap gap-2">
          {ALLERGY_OPTIONS.map((opt) => (
            <Chip key={opt} label={opt} selected={value.allergies.includes(opt)} onToggle={() => toggle("allergies", opt)} />
          ))}
        </div>
        {nonNoneAllergies.length > 0 && (
          <div className="mt-3 flex flex-col gap-2 border-l-2 border-primary-fixed pl-4">
            <div className="text-xs text-text-muted tracking-wide">Severity per allergy:</div>
            {nonNoneAllergies.map((a) => (
              <div key={a} className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm font-medium">{a}</span>
                <div className="flex gap-1.5">
                  {SEVERITY_ORDER.map((sev) => (
                    <Chip
                      key={sev}
                      label={sev}
                      selected={value.allergy_severity[a] === sev}
                      onToggle={() => setSeverity(a, sev)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Medications + blood thinner follow-up */}
      <div>
        <div className="text-sm font-semibold mb-2">Current medications</div>
        <div className="flex flex-wrap gap-2">
          {MEDICATION_OPTIONS.map((opt) => (
            <Chip
              key={opt}
              label={opt}
              selected={value.medications.includes(opt)}
              onToggle={() => toggle("medications", opt)}
            />
          ))}
        </div>
        {onBloodThinner && (
          <div className="mt-3 border-l-2 border-primary-fixed pl-4">
            <div className="text-xs text-text-muted tracking-wide mb-2">Which blood thinner?</div>
            <div className="flex flex-wrap gap-2">
              {BLOOD_THINNERS.map((bt) => (
                <Chip
                  key={bt}
                  label={bt}
                  selected={value.blood_thinner_name === bt}
                  onToggle={() =>
                    onChange({ ...value, blood_thinner_name: value.blood_thinner_name === bt ? null : bt })
                  }
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Conditions + condition-specific follow-ups */}
      <div>
        <div className="text-sm font-semibold mb-2">Existing conditions</div>
        <div className="flex flex-wrap gap-2">
          {CONDITION_OPTIONS.map((opt) => (
            <Chip
              key={opt}
              label={opt}
              selected={value.conditions.includes(opt)}
              onToggle={() => toggle("conditions", opt)}
            />
          ))}
        </div>

        {hasDiabetes && (
          <div className="mt-3 border-l-2 border-primary-fixed pl-4">
            <div className="text-xs text-text-muted tracking-wide mb-2">Diabetes type?</div>
            <div className="flex gap-2">
              {(["type1", "type2", "gestational"] as const).map((t) => (
                <Chip
                  key={t}
                  label={t === "type1" ? "Type 1" : t === "type2" ? "Type 2" : "Gestational"}
                  selected={value.diabetes_type === t}
                  onToggle={() => onChange({ ...value, diabetes_type: value.diabetes_type === t ? null : t })}
                />
              ))}
            </div>
          </div>
        )}

        {hasHeartFailure && (
          <div className="mt-3 border-l-2 border-primary-fixed pl-4">
            <div className="text-xs text-text-muted tracking-wide mb-2">NYHA class?</div>
            <div className="flex gap-2">
              {(["I", "II", "III", "IV"] as const).map((c) => (
                <Chip
                  key={c}
                  label={`Class ${c}`}
                  selected={value.heart_failure_class === c}
                  onToggle={() =>
                    onChange({ ...value, heart_failure_class: value.heart_failure_class === c ? null : c })
                  }
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Smoking — simple boolean, high clinical signal */}
      <div>
        <div className="text-sm font-semibold mb-2">Do you smoke?</div>
        <div className="flex gap-2">
          <Chip label="Yes" selected={value.smoker === true} onToggle={() => onChange({ ...value, smoker: true })} />
          <Chip
            label="No"
            selected={value.smoker === false}
            onToggle={() => onChange({ ...value, smoker: false })}
          />
        </div>
      </div>
    </div>
  );
}
