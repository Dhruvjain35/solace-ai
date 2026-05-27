"""Drug-drug + drug-allergy + renal/hepatic-dose interaction checker.

Production target is FDB or Medi-Span; this module ships a curated common-pair
table plus a therapeutic-class layer so one rule covers a whole drug class, an
RxNorm-style alias map so brand names and generics resolve to a canonical key,
and a small cross-reactivity map for drug-allergy alerts.

Two design pillars matter clinically:

1. Class-aware rules. `_DRUG_CLASSES` maps each canonical drug to the
   therapeutic classes it belongs to (a drug may be in several). An
   interaction rule may name either a concrete drug or a class token; one
   "ssri + nsaid" rule then covers every SSRI x every NSAID pair.

2. Alert gating. Alert fatigue is the real clinical risk. `check()` runs an
   explicit gating layer: contraindicated/high alerts are NEVER gated;
   moderate/low alerts are suppressed for trivial visits. Suppressed alerts
   are not discarded — they are returned in `summary.suppressed` so the record
   is auditable, never silent.

The production seam is the `InteractionSource` Protocol plus `set_source()`:
swap in an FDB / Medi-Span adapter without touching callers.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Severity model
# --------------------------------------------------------------------------
# Ordered low -> contraindicated. Used for ranking and for gating decisions.
_SEVERITY_RANK: dict[str, int] = {
    "low": 0,
    "moderate": 1,
    "high": 2,
    "contraindicated": 3,
}
# Severities that must always surface, regardless of encounter context.
_NEVER_GATE = {"high", "contraindicated"}


def _sev_rank(sev: str) -> int:
    return _SEVERITY_RANK.get((sev or "").lower(), 0)


# --------------------------------------------------------------------------
# Brand -> generic canonical key
# --------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    "advil": "ibuprofen", "motrin": "ibuprofen", "ibuprofen": "ibuprofen",
    "tylenol": "acetaminophen", "acetaminophen": "acetaminophen", "paracetamol": "acetaminophen",
    "aspirin": "aspirin", "asa": "aspirin", "bayer": "aspirin",
    "naproxen": "naproxen", "aleve": "naproxen",
    "ketorolac": "ketorolac", "toradol": "ketorolac",
    "celecoxib": "celecoxib", "celebrex": "celecoxib",
    "diclofenac": "diclofenac", "voltaren": "diclofenac",
    "meloxicam": "meloxicam", "mobic": "meloxicam",
    "indomethacin": "indomethacin", "indocin": "indomethacin",
    "warfarin": "warfarin", "coumadin": "warfarin",
    "eliquis": "apixaban", "apixaban": "apixaban",
    "xarelto": "rivaroxaban", "rivaroxaban": "rivaroxaban",
    "pradaxa": "dabigatran", "dabigatran": "dabigatran",
    "savaysa": "edoxaban", "edoxaban": "edoxaban",
    "enoxaparin": "enoxaparin", "lovenox": "enoxaparin",
    "heparin": "heparin",
    "clopidogrel": "clopidogrel", "plavix": "clopidogrel",
    "ticagrelor": "ticagrelor", "brilinta": "ticagrelor",
    "lipitor": "atorvastatin", "atorvastatin": "atorvastatin",
    "crestor": "rosuvastatin", "rosuvastatin": "rosuvastatin",
    "simvastatin": "simvastatin", "zocor": "simvastatin",
    "pravastatin": "pravastatin", "pravachol": "pravastatin",
    "lovastatin": "lovastatin", "mevacor": "lovastatin",
    "metformin": "metformin", "glucophage": "metformin",
    "glipizide": "glipizide", "glucotrol": "glipizide",
    "glyburide": "glyburide",
    "insulin": "insulin",
    "lisinopril": "lisinopril", "zestril": "lisinopril", "prinivil": "lisinopril",
    "enalapril": "enalapril", "vasotec": "enalapril",
    "ramipril": "ramipril", "altace": "ramipril",
    "benazepril": "benazepril", "lotensin": "benazepril",
    "losartan": "losartan", "cozaar": "losartan",
    "valsartan": "valsartan", "diovan": "valsartan",
    "olmesartan": "olmesartan", "benicar": "olmesartan",
    "irbesartan": "irbesartan", "avapro": "irbesartan",
    "metoprolol": "metoprolol", "lopressor": "metoprolol", "toprol": "metoprolol",
    "atenolol": "atenolol", "tenormin": "atenolol",
    "carvedilol": "carvedilol", "coreg": "carvedilol",
    "propranolol": "propranolol", "inderal": "propranolol",
    "amlodipine": "amlodipine", "norvasc": "amlodipine",
    "diltiazem": "diltiazem", "cardizem": "diltiazem",
    "verapamil": "verapamil", "calan": "verapamil",
    "hctz": "hydrochlorothiazide", "hydrochlorothiazide": "hydrochlorothiazide",
    "chlorthalidone": "chlorthalidone",
    "furosemide": "furosemide", "lasix": "furosemide",
    "bumetanide": "bumetanide", "bumex": "bumetanide",
    "spironolactone": "spironolactone", "aldactone": "spironolactone",
    "eplerenone": "eplerenone", "inspra": "eplerenone",
    "triamterene": "triamterene",
    "sertraline": "sertraline", "zoloft": "sertraline",
    "fluoxetine": "fluoxetine", "prozac": "fluoxetine",
    "citalopram": "citalopram", "celexa": "citalopram",
    "escitalopram": "escitalopram", "lexapro": "escitalopram",
    "paroxetine": "paroxetine", "paxil": "paroxetine",
    "venlafaxine": "venlafaxine", "effexor": "venlafaxine",
    "duloxetine": "duloxetine", "cymbalta": "duloxetine",
    "trazodone": "trazodone",
    "amitriptyline": "amitriptyline", "elavil": "amitriptyline",
    "nortriptyline": "nortriptyline", "pamelor": "nortriptyline",
    "tramadol": "tramadol", "ultram": "tramadol",
    "oxycodone": "oxycodone", "percocet": "oxycodone", "oxycontin": "oxycodone",
    "hydrocodone": "hydrocodone", "vicodin": "hydrocodone", "norco": "hydrocodone",
    "morphine": "morphine", "ms contin": "morphine",
    "hydromorphone": "hydromorphone", "dilaudid": "hydromorphone",
    "fentanyl": "fentanyl",
    "codeine": "codeine",
    "alprazolam": "alprazolam", "xanax": "alprazolam",
    "lorazepam": "lorazepam", "ativan": "lorazepam",
    "clonazepam": "clonazepam", "klonopin": "clonazepam",
    "diazepam": "diazepam", "valium": "diazepam",
    "temazepam": "temazepam", "restoril": "temazepam",
    "zolpidem": "zolpidem", "ambien": "zolpidem",
    "diphenhydramine": "diphenhydramine", "benadryl": "diphenhydramine",
    "ondansetron": "ondansetron", "zofran": "ondansetron",
    "azithromycin": "azithromycin", "z-pak": "azithromycin", "zithromax": "azithromycin",
    "clarithromycin": "clarithromycin", "biaxin": "clarithromycin",
    "erythromycin": "erythromycin",
    "ciprofloxacin": "ciprofloxacin", "cipro": "ciprofloxacin",
    "levofloxacin": "levofloxacin", "levaquin": "levofloxacin",
    "moxifloxacin": "moxifloxacin", "avelox": "moxifloxacin",
    "amoxicillin": "amoxicillin", "amox": "amoxicillin",
    "ampicillin": "ampicillin",
    "augmentin": "amoxicillin-clavulanate", "amoxicillin-clavulanate": "amoxicillin-clavulanate",
    "penicillin": "penicillin", "pcn": "penicillin",
    "cephalexin": "cephalexin", "keflex": "cephalexin",
    "cefazolin": "cefazolin", "ancef": "cefazolin",
    "ceftriaxone": "ceftriaxone", "rocephin": "ceftriaxone",
    "cefuroxime": "cefuroxime", "ceftin": "cefuroxime",
    "cefdinir": "cefdinir", "omnicef": "cefdinir",
    "meropenem": "meropenem", "imipenem": "imipenem", "ertapenem": "ertapenem",
    "sulfamethoxazole": "sulfamethoxazole", "bactrim": "sulfamethoxazole-trimethoprim",
    "sulfamethoxazole-trimethoprim": "sulfamethoxazole-trimethoprim", "septra": "sulfamethoxazole-trimethoprim",
    "amiodarone": "amiodarone",
    "sotalol": "sotalol",
    "digoxin": "digoxin", "lanoxin": "digoxin",
    "potassium": "potassium chloride", "kcl": "potassium chloride",
    "sildenafil": "sildenafil", "viagra": "sildenafil",
    "tadalafil": "tadalafil", "cialis": "tadalafil",
    "vardenafil": "vardenafil", "levitra": "vardenafil",
    "nitroglycerin": "nitroglycerin", "ntg": "nitroglycerin",
    "isosorbide": "isosorbide", "imdur": "isosorbide",
    "gabapentin": "gabapentin", "neurontin": "gabapentin",
    "pregabalin": "pregabalin", "lyrica": "pregabalin",
    "ketoconazole": "ketoconazole",
    "fluconazole": "fluconazole", "diflucan": "fluconazole",
    "vancomycin": "vancomycin",
    "lithium": "lithium",
    "methotrexate": "methotrexate",
    "prednisone": "prednisone",
    "allopurinol": "allopurinol",
}


# --------------------------------------------------------------------------
# Therapeutic class map: canonical drug -> set of class tokens it belongs to.
# Interaction rules may reference a class token, so one rule covers the class.
# --------------------------------------------------------------------------
_DRUG_CLASSES: dict[str, set[str]] = {
    # NSAIDs
    "ibuprofen": {"nsaid"},
    "naproxen": {"nsaid"},
    "ketorolac": {"nsaid"},
    "celecoxib": {"nsaid"},
    "diclofenac": {"nsaid"},
    "meloxicam": {"nsaid"},
    "indomethacin": {"nsaid"},
    "aspirin": {"nsaid", "antiplatelet"},
    # SSRI / SNRI -> serotonergic
    "sertraline": {"ssri", "serotonergic"},
    "fluoxetine": {"ssri", "serotonergic"},
    "citalopram": {"ssri", "serotonergic", "qt_prolonging"},
    "escitalopram": {"ssri", "serotonergic", "qt_prolonging"},
    "paroxetine": {"ssri", "serotonergic"},
    "venlafaxine": {"snri", "serotonergic"},
    "duloxetine": {"snri", "serotonergic"},
    "trazodone": {"serotonergic"},
    "amitriptyline": {"tca", "serotonergic", "qt_prolonging"},
    "nortriptyline": {"tca", "qt_prolonging"},
    # Opioids -> CNS depressants; tramadol is also serotonergic
    "tramadol": {"opioid", "serotonergic", "cns_depressant"},
    "oxycodone": {"opioid", "cns_depressant"},
    "hydrocodone": {"opioid", "cns_depressant"},
    "morphine": {"opioid", "cns_depressant"},
    "hydromorphone": {"opioid", "cns_depressant"},
    "fentanyl": {"opioid", "cns_depressant"},
    "codeine": {"opioid", "cns_depressant"},
    # Benzodiazepines + Z-drugs -> CNS depressants
    "alprazolam": {"benzodiazepine", "cns_depressant"},
    "lorazepam": {"benzodiazepine", "cns_depressant"},
    "clonazepam": {"benzodiazepine", "cns_depressant"},
    "diazepam": {"benzodiazepine", "cns_depressant"},
    "temazepam": {"benzodiazepine", "cns_depressant"},
    "zolpidem": {"z_drug", "cns_depressant"},
    "diphenhydramine": {"anticholinergic", "cns_depressant"},
    # Anticoagulants / antiplatelets
    "warfarin": {"anticoagulant"},
    "apixaban": {"anticoagulant", "doac"},
    "rivaroxaban": {"anticoagulant", "doac"},
    "dabigatran": {"anticoagulant", "doac"},
    "edoxaban": {"anticoagulant", "doac"},
    "enoxaparin": {"anticoagulant"},
    "heparin": {"anticoagulant"},
    "clopidogrel": {"antiplatelet"},
    "ticagrelor": {"antiplatelet"},
    # Statins
    "atorvastatin": {"statin"},
    "rosuvastatin": {"statin"},
    "simvastatin": {"statin", "cyp3a4_statin"},
    "lovastatin": {"statin", "cyp3a4_statin"},
    "pravastatin": {"statin"},
    # RAAS + potassium-sparing -> hyperkalemia cluster
    "lisinopril": {"acei", "raas"},
    "enalapril": {"acei", "raas"},
    "ramipril": {"acei", "raas"},
    "benazepril": {"acei", "raas"},
    "losartan": {"arb", "raas"},
    "valsartan": {"arb", "raas"},
    "olmesartan": {"arb", "raas"},
    "irbesartan": {"arb", "raas"},
    "spironolactone": {"k_sparing_diuretic"},
    "eplerenone": {"k_sparing_diuretic"},
    "triamterene": {"k_sparing_diuretic"},
    "potassium chloride": {"potassium_supplement"},
    # Beta-blockers
    "metoprolol": {"beta_blocker"},
    "atenolol": {"beta_blocker"},
    "carvedilol": {"beta_blocker"},
    "propranolol": {"beta_blocker"},
    # Non-dihydropyridine CCBs (rate-controlling)
    "diltiazem": {"nondhp_ccb", "cyp3a4_inhibitor"},
    "verapamil": {"nondhp_ccb", "cyp3a4_inhibitor"},
    # Diuretics that cause hypokalemia
    "furosemide": {"loop_diuretic", "hypokalemic_diuretic"},
    "bumetanide": {"loop_diuretic", "hypokalemic_diuretic"},
    "hydrochlorothiazide": {"thiazide_diuretic", "hypokalemic_diuretic"},
    "chlorthalidone": {"thiazide_diuretic", "hypokalemic_diuretic"},
    # Macrolides + azoles -> CYP3A4 inhibitors; macrolides + FQs QT-prolonging
    "azithromycin": {"macrolide", "qt_prolonging"},
    "clarithromycin": {"macrolide", "cyp3a4_inhibitor", "qt_prolonging"},
    "erythromycin": {"macrolide", "cyp3a4_inhibitor", "qt_prolonging"},
    "ketoconazole": {"azole_antifungal", "cyp3a4_inhibitor"},
    "fluconazole": {"azole_antifungal", "cyp3a4_inhibitor"},
    "ciprofloxacin": {"fluoroquinolone", "qt_prolonging"},
    "levofloxacin": {"fluoroquinolone", "qt_prolonging"},
    "moxifloxacin": {"fluoroquinolone", "qt_prolonging"},
    # Antiarrhythmics
    "amiodarone": {"antiarrhythmic", "qt_prolonging", "cyp3a4_inhibitor"},
    "sotalol": {"antiarrhythmic", "qt_prolonging"},
    # Antiemetics
    "ondansetron": {"qt_prolonging"},
    # Nitrates / PDE5
    "nitroglycerin": {"nitrate"},
    "isosorbide": {"nitrate"},
    "sildenafil": {"pde5_inhibitor"},
    "tadalafil": {"pde5_inhibitor"},
    "vardenafil": {"pde5_inhibitor"},
    # Beta-lactams (for allergy cross-reactivity)
    "penicillin": {"penicillin", "beta_lactam"},
    "amoxicillin": {"penicillin", "beta_lactam"},
    "ampicillin": {"penicillin", "beta_lactam"},
    "amoxicillin-clavulanate": {"penicillin", "beta_lactam"},
    "cephalexin": {"cephalosporin", "beta_lactam"},
    "cefazolin": {"cephalosporin", "beta_lactam"},
    "ceftriaxone": {"cephalosporin", "beta_lactam"},
    "cefuroxime": {"cephalosporin", "beta_lactam"},
    "cefdinir": {"cephalosporin", "beta_lactam"},
    "meropenem": {"carbapenem", "beta_lactam"},
    "imipenem": {"carbapenem", "beta_lactam"},
    "ertapenem": {"carbapenem", "beta_lactam"},
    "sulfamethoxazole": {"sulfonamide"},
    "sulfamethoxazole-trimethoprim": {"sulfonamide"},
    # Misc
    "digoxin": {"cardiac_glycoside"},
}


def _classes(drug: str) -> set[str]:
    """All tokens that can match an interaction rule for this drug:
    the canonical drug name itself plus every therapeutic class it is in."""
    return {drug} | _DRUG_CLASSES.get(drug, set())


# --------------------------------------------------------------------------
# Interaction rules. Either token may be a concrete drug or a class token.
# Format: (token_a, token_b, severity, reason)
# A class token (e.g. "ssri") expands to cover every member of that class.
# --------------------------------------------------------------------------
_PAIRS: list[tuple[str, str, str, str]] = [
    # Bleeding — anticoagulant + NSAID/antiplatelet (class-wide)
    ("warfarin", "nsaid", "high", "GI bleeding + INR elevation"),
    ("warfarin", "antiplatelet", "high", "Increased bleeding risk; INR variability"),
    ("doac", "nsaid", "moderate", "Additive bleeding risk"),
    ("doac", "antiplatelet", "moderate", "Additive bleeding risk"),
    ("anticoagulant", "anticoagulant", "high", "Duplicate anticoagulation — major bleeding risk"),
    # Warfarin CYP / metabolic interactions
    ("warfarin", "fluoroquinolone", "high", "Major INR elevation via CYP inhibition"),
    ("warfarin", "macrolide", "moderate", "INR elevation reported"),
    ("warfarin", "amiodarone", "high", "Marked INR rise; reduce warfarin ~50%"),
    ("warfarin", "sulfonamide", "high", "Marked INR elevation; CYP2C9 inhibition"),
    ("warfarin", "azole_antifungal", "high", "Major INR elevation via CYP2C9 inhibition"),
    # DOAC P-gp / CYP3A4
    ("rivaroxaban", "azole_antifungal", "high", "P-gp + CYP3A4 inhibition raises rivaroxaban levels"),
    ("dabigatran", "azole_antifungal", "high", "P-gp inhibition raises dabigatran"),
    ("doac", "cyp3a4_inhibitor", "moderate", "CYP3A4/P-gp inhibition may raise DOAC levels"),
    # PDE5 + nitrate — absolute contraindication
    ("pde5_inhibitor", "nitrate", "contraindicated", "Severe, potentially fatal hypotension — CONTRAINDICATED"),
    # Statin myopathy
    ("cyp3a4_statin", "cyp3a4_inhibitor", "high", "Severe myopathy/rhabdomyolysis risk via CYP3A4 inhibition"),
    ("cyp3a4_statin", "amiodarone", "high", "Myopathy risk; cap simvastatin at 20 mg"),
    ("statin", "macrolide", "moderate", "Increased statin levels; myopathy risk"),
    # Serotonin syndrome — any two serotonergic agents
    ("serotonergic", "serotonergic", "moderate", "Additive serotonergic load — serotonin syndrome risk"),
    # GI bleed — SSRI/SNRI + NSAID
    ("ssri", "nsaid", "moderate", "Antiplatelet effect of SSRI plus NSAID — GI bleed risk"),
    ("snri", "nsaid", "moderate", "Antiplatelet effect of SNRI plus NSAID — GI bleed risk"),
    # QT prolongation — any two QT-prolonging agents
    ("qt_prolonging", "qt_prolonging", "moderate", "Additive QT prolongation — torsades risk"),
    ("amiodarone", "fluoroquinolone", "high", "Major QT prolongation; arrhythmia risk"),
    ("amiodarone", "macrolide", "high", "Major QT prolongation; arrhythmia risk"),
    # Digoxin toxicity
    ("digoxin", "amiodarone", "high", "Digoxin toxicity; halve digoxin dose"),
    ("digoxin", "verapamil", "high", "Raised digoxin levels — toxicity risk"),
    ("digoxin", "k_sparing_diuretic", "moderate", "Digoxin toxicity risk"),
    ("digoxin", "hypokalemic_diuretic", "moderate", "Hypokalemia potentiates digoxin toxicity"),
    # Hyperkalemia cluster
    ("raas", "k_sparing_diuretic", "moderate", "Hyperkalemia risk — monitor potassium"),
    ("raas", "potassium_supplement", "moderate", "Hyperkalemia risk — monitor potassium"),
    ("k_sparing_diuretic", "potassium_supplement", "high", "Significant hyperkalemia risk"),
    ("raas", "raas", "moderate", "Dual RAAS blockade — hyperkalemia and AKI risk"),
    ("raas", "nsaid", "moderate", "Reduced antihypertensive effect; AKI risk (triple-whammy with diuretic)"),
    # CNS / respiratory depression — opioid + any CNS depressant
    ("opioid", "benzodiazepine", "high", "Respiratory depression — FDA black box warning"),
    ("opioid", "z_drug", "high", "Additive CNS/respiratory depression"),
    ("opioid", "cns_depressant", "moderate", "Additive sedation — counsel on CNS depression"),
    # Bradycardia — beta-blocker + non-DHP CCB
    ("beta_blocker", "nondhp_ccb", "high", "Severe bradycardia and heart block risk"),
    # Lithium
    ("lithium", "nsaid", "high", "Reduced lithium clearance — lithium toxicity"),
    ("lithium", "raas", "moderate", "Reduced lithium clearance — monitor levels"),
    ("lithium", "hypokalemic_diuretic", "moderate", "Thiazide reduces lithium clearance — toxicity risk"),
    # Methotrexate
    ("methotrexate", "nsaid", "high", "Reduced methotrexate clearance — marrow toxicity"),
    ("methotrexate", "sulfonamide", "high", "Additive marrow toxicity; reduced MTX clearance"),
    # Metformin + contrast
    ("metformin", "iv contrast", "moderate", "Hold metformin 48h around contrast in CKD"),
    # Allopurinol
    ("allopurinol", "azathioprine", "high", "Azathioprine toxicity — xanthine oxidase inhibition"),
]


# --------------------------------------------------------------------------
# Drug-allergy cross-reactivity. Maps an allergy class/drug to the classes
# that share a cross-reactivity risk, with severity + reason.
# --------------------------------------------------------------------------
_CROSS_REACTIVITY: list[tuple[str, str, str, str]] = [
    ("penicillin", "cephalosporin", "moderate",
     "Penicillin allergy — ~1-2% cross-reactivity with cephalosporins (higher for 1st-gen)"),
    ("penicillin", "carbapenem", "moderate",
     "Penicillin allergy — low but documented cross-reactivity with carbapenems"),
    ("cephalosporin", "penicillin", "moderate",
     "Cephalosporin allergy — possible cross-reactivity with penicillins"),
    ("nsaid", "nsaid", "high",
     "Reported NSAID/aspirin hypersensitivity — class-wide reaction risk (avoid all NSAIDs)"),
    ("sulfonamide", "sulfonamide", "moderate",
     "Sulfonamide allergy — applies across sulfonamide antibiotics"),
]


# --------------------------------------------------------------------------
# Renal dosing — drug -> (eGFR/CrCl threshold mL/min, guidance, severity)
# --------------------------------------------------------------------------
_RENAL_FLAGS: dict[str, tuple[float, str, str]] = {
    "metformin": (30, "contraindicated if eGFR <30; reduce dose if 30-45", "high"),
    "apixaban": (15, "use with caution; renal-adjusted dose if SCr >=1.5 + age >=80 + wt <=60kg", "moderate"),
    "rivaroxaban": (15, "avoid if eGFR <15; reduced dose if 15-49", "high"),
    "dabigatran": (30, "avoid if eGFR <30", "high"),
    "edoxaban": (15, "avoid if eGFR <15; reduce dose if 15-50", "high"),
    "enoxaparin": (30, "reduce to once-daily dosing if CrCl <30", "moderate"),
    "gabapentin": (60, "renal dose adjustment required", "moderate"),
    "pregabalin": (60, "renal dose adjustment required", "moderate"),
    "ciprofloxacin": (30, "extend dosing interval if eGFR <30", "moderate"),
    "levofloxacin": (50, "renal dose adjustment if CrCl <50", "moderate"),
    "vancomycin": (60, "trough/AUC-guided dosing required", "moderate"),
    "sulfamethoxazole-trimethoprim": (30, "reduce dose by 50% if CrCl 15-30; avoid if <15", "moderate"),
    "fluconazole": (50, "reduce maintenance dose by 50% if CrCl <50", "low"),
    "allopurinol": (60, "reduce dose with renal impairment to limit toxicity", "moderate"),
    "lithium": (60, "renally cleared — toxicity risk; monitor levels closely", "high"),
}


# --------------------------------------------------------------------------
# Hepatic dosing — drug -> guidance keyed on Child-Pugh class.
# Each entry: drug -> {child_pugh_class: (severity, guidance)}.
# Classes: A (mild), B (moderate), C (severe).
# --------------------------------------------------------------------------
_HEPATIC_FLAGS: dict[str, dict[str, tuple[str, str]]] = {
    "apixaban": {
        "B": ("moderate", "use with caution in Child-Pugh B"),
        "C": ("high", "not recommended in Child-Pugh C — coagulopathy"),
    },
    "rivaroxaban": {
        "B": ("high", "avoid in Child-Pugh B/C with coagulopathy"),
        "C": ("contraindicated", "contraindicated in Child-Pugh B/C hepatic disease"),
    },
    "dabigatran": {
        "C": ("high", "avoid in severe hepatic impairment"),
    },
    "atorvastatin": {
        "B": ("high", "avoid statins in active liver disease / Child-Pugh B/C"),
        "C": ("contraindicated", "contraindicated in active liver disease"),
    },
    "simvastatin": {
        "B": ("high", "avoid statins in active liver disease / Child-Pugh B/C"),
        "C": ("contraindicated", "contraindicated in active liver disease"),
    },
    "rosuvastatin": {
        "B": ("high", "avoid statins in active liver disease"),
        "C": ("contraindicated", "contraindicated in active liver disease"),
    },
    "acetaminophen": {
        "B": ("moderate", "limit to <=2 g/day in significant hepatic impairment"),
        "C": ("high", "limit to <=2 g/day; avoid in decompensated cirrhosis"),
    },
    "tramadol": {
        "C": ("moderate", "extend dosing interval; reduce dose in severe hepatic impairment"),
    },
    "morphine": {
        "B": ("moderate", "reduce dose / extend interval in hepatic impairment"),
        "C": ("high", "marked accumulation — large dose reduction needed"),
    },
    "oxycodone": {
        "B": ("moderate", "reduce starting dose by 1/3 to 1/2 in hepatic impairment"),
        "C": ("high", "marked accumulation — large dose reduction needed"),
    },
    "diazepam": {
        "B": ("moderate", "prolonged sedation — prefer lorazepam (no active metabolites)"),
        "C": ("high", "avoid long-acting benzodiazepines in hepatic impairment"),
    },
    "methotrexate": {
        "B": ("high", "hepatotoxic — avoid in significant liver disease"),
        "C": ("contraindicated", "contraindicated in significant hepatic disease"),
    },
}


# --------------------------------------------------------------------------
# Duplicate-therapy detection — classes where two members at once is a
# therapeutic-duplication concern worth surfacing.
# --------------------------------------------------------------------------
_DUPLICATE_CLASSES: dict[str, tuple[str, str]] = {
    "nsaid": ("moderate", "Two NSAIDs — no added benefit, additive GI/renal toxicity"),
    "opioid": ("moderate", "Multiple opioids — review for unintended duplication"),
    "benzodiazepine": ("moderate", "Multiple benzodiazepines — additive sedation, review duplication"),
    "ssri": ("high", "Two SSRIs — serotonin syndrome risk, almost never intended"),
    "statin": ("moderate", "Two statins — duplicate therapy, additive myopathy risk"),
    "acei": ("high", "Two ACE inhibitors — duplicate therapy, hyperkalemia/AKI risk"),
    "arb": ("high", "Two ARBs — duplicate therapy, hyperkalemia/AKI risk"),
    "anticoagulant": ("high", "Two anticoagulants — major bleeding risk unless bridging"),
    "beta_blocker": ("moderate", "Two beta-blockers — additive bradycardia/hypotension"),
    "ppi": ("low", "Two proton-pump inhibitors — duplicate therapy"),
}


# --------------------------------------------------------------------------
# Encounter gating: complaints that make moderate/low alerts trivial noise.
# --------------------------------------------------------------------------
_TRIVIAL_COMPLAINT_MARKERS = (
    "sprain", "rash", "school note", "work note", "physical exam",
    "wart", "minor cut", "med refill", "medication refill", "suture removal",
    "ear wax", "ingrown", "tinea", "athlete's foot", "form completion",
)


def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    return _ALIASES.get(n, n)


# ==========================================================================
# Cockcroft-Gault helper
# ==========================================================================
def cockcroft_gault(
    *,
    age_years: float,
    weight_kg: float,
    serum_creatinine_mg_dl: float,
    is_female: bool,
) -> float | None:
    """Estimate creatinine clearance (mL/min) via Cockcroft-Gault.

    CrCl = ((140 - age) * weight_kg * sex_factor) / (72 * SCr)
    sex_factor = 0.85 for female, 1.0 for male.

    Returns None if inputs are non-physiologic so callers can skip renal
    gating rather than act on a garbage number.
    """
    try:
        if age_years <= 0 or weight_kg <= 0 or serum_creatinine_mg_dl <= 0:
            return None
        sex_factor = 0.85 if is_female else 1.0
        crcl = ((140 - age_years) * weight_kg * sex_factor) / (72 * serum_creatinine_mg_dl)
        return round(max(crcl, 0.0), 1)
    except Exception:  # pragma: no cover - defensive
        return None


# ==========================================================================
# Pluggable interaction source — the FDB / Medi-Span production seam
# ==========================================================================
@runtime_checkable
class InteractionSource(Protocol):
    """Production swap seam. An FDB / Medi-Span adapter implements this
    Protocol and is registered via `set_source()`; `check()` then delegates
    drug-drug + drug-allergy lookups to it instead of the curated tables.

    All other layers (renal, hepatic, duplicate therapy, gating) are reused
    unchanged, so a vendor adapter only needs to cover the lookups vendors
    actually price.
    """

    def drug_drug(self, canon_meds: list[str]) -> list[dict[str, Any]]:
        """Return raw drug-drug alerts: dicts with keys a, b, severity, reason."""
        ...

    def drug_allergy(
        self, canon_meds: list[str], canon_allergies: list[str]
    ) -> list[dict[str, Any]]:
        """Return raw drug-allergy alerts: dicts with keys med, severity, reason."""
        ...


class _CuratedSource:
    """Default in-process source backed by the curated class-aware tables."""

    def drug_drug(self, canon_meds: list[str]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for i, a in enumerate(canon_meds):
            a_tokens = _classes(a)
            for b in canon_meds[i + 1:]:
                b_tokens = _classes(b)
                for ta, tb, sev, reason in _PAIRS:
                    matched = (
                        (ta in a_tokens and tb in b_tokens)
                        or (ta in b_tokens and tb in a_tokens)
                    )
                    if not matched:
                        continue
                    key = tuple(sorted((a, b))) + (reason,)
                    if key in seen:
                        continue
                    seen.add(key)
                    alerts.append(
                        {"a": a, "b": b, "severity": sev, "reason": reason}
                    )
        return alerts

    def drug_allergy(
        self, canon_meds: list[str], canon_allergies: list[str]
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        allergy_token_set: set[str] = set()
        for a in canon_allergies:
            allergy_token_set |= _classes(a)

        for med in canon_meds:
            med_tokens = _classes(med)
            # Direct allergy: the exact drug (or a class) is on the allergy list.
            if med in canon_allergies:
                alerts.append({
                    "med": med, "severity": "high",
                    "reason": f"patient-reported allergy to {med}",
                })
                continue
            direct_class_hit = med_tokens & set(canon_allergies)
            if direct_class_hit:
                alerts.append({
                    "med": med, "severity": "high",
                    "reason": f"patient-reported allergy matches {med} "
                              f"({', '.join(sorted(direct_class_hit))})",
                })
                continue
            # Cross-reactivity: allergy class -> a different drug class.
            for allergy_token, target_class, sev, reason in _CROSS_REACTIVITY:
                if allergy_token in allergy_token_set and target_class in med_tokens:
                    # Skip if it's literally the same class as the allergy
                    # (already covered by the direct-hit branch above).
                    if allergy_token == target_class and allergy_token in (med_tokens & allergy_token_set) - med_tokens:
                        continue
                    alerts.append({
                        "med": med, "severity": sev,
                        "reason": reason,
                    })
                    break
        return alerts


_source: InteractionSource = _CuratedSource()


def set_source(source: InteractionSource) -> None:
    """Register a production interaction source (FDB / Medi-Span adapter).

    The adapter must satisfy the `InteractionSource` Protocol. After this
    call every `check()` delegates drug-drug + drug-allergy lookups to it;
    renal/hepatic/duplicate/gating logic is unchanged.
    """
    global _source
    if not isinstance(source, InteractionSource):
        raise TypeError(
            "source must implement the InteractionSource Protocol "
            "(drug_drug, drug_allergy)"
        )
    _source = source
    log.info("drug_interactions source set to %s", type(source).__name__)


def reset_source() -> None:
    """Restore the default curated source (useful for tests)."""
    global _source
    _source = _CuratedSource()


# ==========================================================================
# Detection helpers
# ==========================================================================
def _renal_alerts(
    canon_meds: list[str], crcl: float | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if crcl is None:
        return out
    for med in canon_meds:
        flag = _RENAL_FLAGS.get(med)
        if flag and crcl < flag[0]:
            threshold, guidance, severity = flag
            out.append({
                "med": med,
                "egfr": crcl,           # legacy key — CrCl/eGFR estimate
                "crcl": crcl,
                "threshold": threshold,
                "severity": severity,
                "guidance": guidance,
            })
    return out


def _hepatic_alerts(
    canon_meds: list[str], child_pugh: str | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not child_pugh:
        return out
    cp = child_pugh.strip().upper()
    if cp not in {"A", "B", "C"}:
        return out
    for med in canon_meds:
        table = _HEPATIC_FLAGS.get(med)
        if not table:
            continue
        # A flag fires at its class and every more-severe class.
        applicable: tuple[str, str] | None = None
        for cls in ("A", "B", "C"):
            if cls in table and cls <= cp:
                applicable = table[cls]
        if applicable:
            severity, guidance = applicable
            out.append({
                "med": med,
                "child_pugh": cp,
                "severity": severity,
                "guidance": guidance,
            })
    return out


def _duplicate_alerts(canon_meds: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_class: dict[str, list[str]] = {}
    for med in canon_meds:
        for cls in _DRUG_CLASSES.get(med, set()):
            by_class.setdefault(cls, []).append(med)
    for cls, (severity, reason) in _DUPLICATE_CLASSES.items():
        members = sorted(set(by_class.get(cls, [])))
        if len(members) >= 2:
            out.append({
                "drug_class": cls,
                "members": members,
                "severity": severity,
                "reason": reason,
            })
    return out


def _is_trivial_visit(complaint: str) -> bool:
    cc = (complaint or "").lower()
    return any(marker in cc for marker in _TRIVIAL_COMPLAINT_MARKERS)


# ==========================================================================
# Alert gating layer
# ==========================================================================
def _gate(
    alerts: list[dict[str, Any]], *, trivial_visit: bool, category: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split alerts into (surfaced, suppressed).

    Gating contract:
      * contraindicated + high  -> ALWAYS surfaced, never gated.
      * moderate + low          -> suppressed only on a trivial visit.
    Suppressed alerts are not dropped — the caller folds them into
    `summary.suppressed` so the decision is auditable, not silent.
    """
    surfaced: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for a in alerts:
        sev = (a.get("severity") or "low").lower()
        if sev in _NEVER_GATE:
            surfaced.append(a)
            continue
        if trivial_visit:
            suppressed.append({
                **a,
                "category": category,
                "suppressed_reason": "moderate/low alert gated for trivial encounter",
            })
        else:
            surfaced.append(a)
    return surfaced, suppressed


def _rank(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Severity-ranked: contraindicated -> high -> moderate -> low."""
    return sorted(
        alerts, key=lambda a: _sev_rank(a.get("severity", "low")), reverse=True
    )


# ==========================================================================
# Public API
# ==========================================================================
def check(
    meds: list[str],
    allergies: list[str] | None = None,
    *,
    egfr: float | None = None,
    crcl: float | None = None,
    child_pugh: str | None = None,
    complaint: str = "",
) -> dict[str, Any]:
    """Run the full interaction panel for an encounter.

    Args:
        meds: drug names (brand or generic) — current + proposed.
        allergies: patient-reported drug allergies (drug or class names).
        egfr / crcl: renal function in mL/min. Either may be passed;
            `crcl` wins if both are given. Pass the Cockcroft-Gault
            estimate from `cockcroft_gault()` when labs allow.
        child_pugh: hepatic function class — "A", "B", or "C".
        complaint: active chief complaint, used by the gating layer.

    Returns a dict that is BACKWARD-COMPATIBLE with the original contract.
    Legacy keys are preserved exactly:
        drug_drug    - surfaced drug-drug alerts (a, b, severity, reason)
        drug_allergy - surfaced drug-allergy alerts (med, reason, ...)
        renal        - renal-dose alerts (med, egfr, guidance, ...)
        any_high     - bool: any surfaced alert is high or contraindicated

    New keys layered on top (additive, non-breaking):
        hepatic           - Child-Pugh dosing alerts
        duplicate_therapy - duplicate-class alerts
        summary           - {highest_severity, counts, gated, suppressed[]}
    """
    canon_meds = list(dict.fromkeys(_canon(m) for m in meds if m))
    canon_allergies = [_canon(a) for a in (allergies or []) if a]
    renal_function = crcl if crcl is not None else egfr

    # ---- raw detection (drug-drug + drug-allergy via the pluggable source)
    raw_pairs = _rank(_source.drug_drug(canon_meds))
    raw_allergy = _rank(_source.drug_allergy(canon_meds, canon_allergies))
    raw_renal = _rank(_renal_alerts(canon_meds, renal_function))
    raw_hepatic = _rank(_hepatic_alerts(canon_meds, child_pugh))
    raw_duplicate = _rank(_duplicate_alerts(canon_meds))

    # ---- gating: high/contraindicated always pass; moderate/low gated on
    #      trivial encounters. Suppressed alerts are kept for the summary.
    trivial = _is_trivial_visit(complaint)
    pair_alerts, sup_pairs = _gate(raw_pairs, trivial_visit=trivial, category="drug_drug")
    allergy_alerts, sup_allergy = _gate(raw_allergy, trivial_visit=trivial, category="drug_allergy")
    renal_alerts, sup_renal = _gate(raw_renal, trivial_visit=trivial, category="renal")
    hepatic_alerts, sup_hepatic = _gate(raw_hepatic, trivial_visit=trivial, category="hepatic")
    dup_alerts, sup_dup = _gate(raw_duplicate, trivial_visit=trivial, category="duplicate_therapy")

    suppressed = sup_pairs + sup_allergy + sup_renal + sup_hepatic + sup_dup

    surfaced_all = (
        pair_alerts + allergy_alerts + renal_alerts + hepatic_alerts + dup_alerts
    )
    if surfaced_all:
        highest = max(_sev_rank(a.get("severity", "low")) for a in surfaced_all)
        highest_sev = next(
            s for s, r in _SEVERITY_RANK.items() if r == highest
        )
    else:
        highest_sev = "none"

    summary = {
        "highest_severity": highest_sev,
        "counts": {
            "drug_drug": len(pair_alerts),
            "drug_allergy": len(allergy_alerts),
            "renal": len(renal_alerts),
            "hepatic": len(hepatic_alerts),
            "duplicate_therapy": len(dup_alerts),
        },
        "gated": trivial,
        "suppressed": suppressed,
    }

    return {
        # ---- legacy contract (do not rename) ----
        "drug_drug": pair_alerts,
        "drug_allergy": allergy_alerts,
        "renal": renal_alerts,
        "any_high": any(
            _sev_rank(a.get("severity", "low")) >= _SEVERITY_RANK["high"]
            for a in surfaced_all
        ),
        # ---- additive depth ----
        "hepatic": hepatic_alerts,
        "duplicate_therapy": dup_alerts,
        "summary": summary,
    }
