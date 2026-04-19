"""Seed the mock EHR DDB table with realistic patient records.

Sriyan Bodla's record is real-ish so he can demo as himself. The 5 canonical
demo patients get records that line up with their current intake transcripts.
Dhruv Jai gets a record so he can demo too.
"""
from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
CMK = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/66c32010-5752-4b1d-8efe-bc317a44cb23"
TABLE = "solace-ehr-patients"

ddb = boto3.client("dynamodb", region_name=REGION)


def ensure_table() -> None:
    try:
        ddb.describe_table(TableName=TABLE)
        print(f"  [ok]    {TABLE} exists")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    ddb.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "mrn", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "mrn", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "name_lower", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "hospital_name-index",
            "KeySchema": [
                {"AttributeName": "hospital_id", "KeyType": "HASH"},
                {"AttributeName": "name_lower", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        SSESpecification={"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": CMK},
    )
    ddb.get_waiter("table_exists").wait(TableName=TABLE)
    print(f"  [create] {TABLE}")


RECORDS = [
    # ========== Sriyan ==========
    {
        "mrn": "SB-2026-001",
        "hospital_id": "demo",
        "name": "Sriyan Bodla",
        "name_lower": "sriyan bodla",
        "dob": "2007-03-15",
        "sex": "male",
        "height_cm": 175,
        "weight_kg": 70,
        "bmi": 22.9,
        "blood_type": "O+",
        "primary_care_provider": "Dr. Anjali Patel — Austin Family Medicine (512-555-0140)",
        "insurance": "UT Austin Student Health Plan (BCBS TX) · member 4K8X-9920-4411",
        "emergency_contact": "Praveen Bodla (father) · 512-555-2201",
        "allergies": ["NKDA"],
        "medications": ["Albuterol HFA inhaler — as needed (last refill Jan 2024, unused in 18+ mo)"],
        "conditions": ["Mild intermittent asthma (childhood onset, well-controlled)"],
        "family_history": ["Father: hypertension", "Mother: type 2 diabetes", "Maternal grandfather: MI age 62"],
        "immunizations": ["COVID-19 (bivalent 2023-10)", "Flu 2023-10", "Tdap 2019", "HPV complete"],
        "social_history": "College student at UT Austin (CS). Non-smoker. Alcohol occasionally, ~2 drinks/mo. Exercise 3x/week basketball + gym.",
        "prior_visits": [
            {"date": "2022-11-03", "type": "ED", "facility": "Solace Demo Hospital",
             "chief_complaint": "URI symptoms, fever", "disposition": "discharged home",
             "note": "Viral URI. Supportive care. No antibiotics. Follow up PCP if not improving in 7 days."},
            {"date": "2019-08-12", "type": "Urgent Care", "facility": "CommunityMed Austin",
             "chief_complaint": "Right wrist pain after basketball fall", "disposition": "discharged",
             "note": "Wrist sprain, negative X-ray. Splinted, follow-up PCP. Ice + ibuprofen PRN."},
            {"date": "2018-06-04", "type": "PCP", "facility": "Austin Family Medicine",
             "chief_complaint": "Asthma follow-up", "disposition": "routine",
             "note": "Asthma well-controlled. Continue albuterol PRN. Peak flow normal. Recommend annual f/u."},
        ],
    },

    # ========== Dhruv ==========
    {
        "mrn": "DJ-2026-001",
        "hospital_id": "demo",
        "name": "Dhruv Jai",
        "name_lower": "dhruv jai",
        "dob": "2006-07-22",
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 72,
        "bmi": 22.7,
        "blood_type": "A+",
        "primary_care_provider": "Dr. Marcus Chen — St. David's Primary Care (512-555-0172)",
        "insurance": "UT Austin Student Health Plan (BCBS TX) · member 4K8X-1138-0092",
        "emergency_contact": "Rakesh Jai (father) · 512-555-3314",
        "allergies": ["NKDA"],
        "medications": ["None"],
        "conditions": ["None"],
        "family_history": ["Mother: hypothyroidism"],
        "immunizations": ["COVID-19 (bivalent 2023-11)", "Flu 2023-10", "Tdap 2021", "MMR complete"],
        "social_history": "College student at UT Austin (stats/ML). Non-smoker. Rare alcohol. Runs 3x/week.",
        "prior_visits": [
            {"date": "2024-02-14", "type": "PCP", "facility": "Solace Primary Care",
             "chief_complaint": "Annual physical", "disposition": "routine",
             "note": "Healthy. Labs WNL. No concerns. Continue current lifestyle."},
        ],
    },

    # ========== Canonical demo patients ==========
    {
        "mrn": "MR-1984-0712",
        "hospital_id": "demo",
        "name": "Marcus",
        "name_lower": "marcus",
        "dob": "1986-04-18",
        "sex": "male",
        "height_cm": 183,
        "weight_kg": 92,
        "bmi": 27.5,
        "blood_type": "B+",
        "primary_care_provider": "Dr. Sarah Nguyen — Downtown Cardiology Group (512-555-0199)",
        "insurance": "Blue Cross Blue Shield TX · member 9903-2187-6631",
        "emergency_contact": "Karen Marcus (wife) · 512-555-4490",
        "allergies": ["Penicillin (rash, 2004)"],
        "medications": ["Lisinopril 10 mg daily", "Atorvastatin 20 mg nightly"],
        "conditions": ["Hypertension (dx 2019)", "Hyperlipidemia (dx 2021)"],
        "family_history": ["Father: MI age 55", "Paternal uncle: CABG"],
        "immunizations": ["Flu 2023", "COVID-19 2023", "Pneumovax 2023"],
        "social_history": "Former smoker (quit 2018, 10 pack-year hx). Alcohol 4-6 drinks/wk. Sedentary.",
        "prior_visits": [
            {"date": "2024-01-08", "type": "PCP", "facility": "Downtown Cardiology",
             "chief_complaint": "HTN follow-up", "disposition": "routine",
             "note": "BP 132/84 on lisinopril. Continue current regimen. Recommended lifestyle counseling."},
            {"date": "2021-06-22", "type": "Cardio", "facility": "Heart Hospital of Austin",
             "chief_complaint": "Chest discomfort, atypical", "disposition": "negative workup",
             "note": "Stress test negative. No acute coronary syndrome. Started atorvastatin for LDL 168."},
        ],
    },
    {
        "mrn": "EM-1991-0333",
        "hospital_id": "demo",
        "name": "Elena",
        "name_lower": "elena",
        "dob": "1991-11-02",
        "sex": "female",
        "height_cm": 165,
        "weight_kg": 62,
        "bmi": 22.8,
        "blood_type": "O-",
        "primary_care_provider": "Dr. Jamie Rivera — East Austin Family Medicine",
        "insurance": "UnitedHealthcare · member 7701-3340-8823",
        "emergency_contact": "Sofia Martinez (sister) · 512-555-1167",
        "allergies": ["NKDA"],
        "medications": ["Sertraline 50 mg daily"],
        "conditions": ["Generalized anxiety disorder (dx 2020)"],
        "family_history": ["Mother: depression"],
        "immunizations": ["Tdap 2022", "Flu 2023"],
        "social_history": "Restaurant line cook. Non-smoker. No alcohol. Yoga 2x/week.",
        "prior_visits": [],
    },
    {
        "mrn": "PS-1988-0612",
        "hospital_id": "demo",
        "name": "Priya",
        "name_lower": "priya",
        "dob": "1988-09-30",
        "sex": "female",
        "height_cm": 160,
        "weight_kg": 58,
        "bmi": 22.7,
        "blood_type": "A+",
        "primary_care_provider": "Dr. Emily Park — Austin Neurology Associates",
        "insurance": "Aetna · member 3392-9810-1180",
        "emergency_contact": "Ravi Sharma (husband) · 512-555-2043",
        "allergies": ["Sulfa (hives)"],
        "medications": ["Sumatriptan 50 mg PRN for migraine", "Propranolol 40 mg BID (prophylaxis)"],
        "conditions": ["Chronic migraine without aura (dx 2016)"],
        "family_history": ["Mother: migraine", "Maternal aunt: MS"],
        "immunizations": ["Flu 2023", "COVID-19 2023", "HPV complete"],
        "social_history": "Software engineer. Non-smoker. Moderate coffee (3-4 cups/day).",
        "prior_visits": [
            {"date": "2023-07-14", "type": "Neuro", "facility": "Austin Neurology",
             "chief_complaint": "Migraine frequency increasing", "disposition": "routine",
             "note": "Started propranolol for prophylaxis. Continue sumatriptan PRN."},
        ],
    },
    {
        "mrn": "JT-2001-0205",
        "hospital_id": "demo",
        "name": "James",
        "name_lower": "james",
        "dob": "2001-02-05",
        "sex": "male",
        "height_cm": 188,
        "weight_kg": 84,
        "bmi": 23.8,
        "blood_type": "AB+",
        "primary_care_provider": "Dr. Alex Kim — Campus Health UT",
        "insurance": "UT Austin Student Health Plan (BCBS TX) · member 4K8X-5528-1190",
        "emergency_contact": "Linda Taylor (mother) · 512-555-6610",
        "allergies": ["NKDA"],
        "medications": ["None"],
        "conditions": ["None"],
        "family_history": ["Paternal grandfather: type 2 diabetes"],
        "immunizations": ["Flu 2023", "Tdap 2019", "COVID-19 2022"],
        "social_history": "UT Austin senior, engineering. Intramural basketball. Non-smoker. Alcohol 4-6 drinks/wk.",
        "prior_visits": [
            {"date": "2022-03-18", "type": "Urgent Care", "facility": "Campus Health UT",
             "chief_complaint": "Left ankle sprain, basketball", "disposition": "discharged",
             "note": "Grade II ankle sprain. RICE, crutches 5 days. Follow-up if not improving."},
        ],
    },
    {
        "mrn": "SG-1998-1117",
        "hospital_id": "demo",
        "name": "Sofia",
        "name_lower": "sofia",
        "dob": "1998-08-11",
        "sex": "female",
        "height_cm": 168,
        "weight_kg": 64,
        "bmi": 22.7,
        "blood_type": "O+",
        "primary_care_provider": "Dr. Jamie Rivera — East Austin Family Medicine",
        "insurance": "Medicaid TX · member 5501-2380-7712",
        "emergency_contact": "Isabel Garcia (mother) · 512-555-8819",
        "allergies": ["Latex (contact dermatitis)"],
        "medications": ["Levothyroxine 75 mcg daily"],
        "conditions": ["Hypothyroidism (dx 2022)"],
        "family_history": ["Mother: hypothyroidism", "Sister: hypothyroidism"],
        "immunizations": ["Flu 2023", "Tdap 2018"],
        "social_history": "Part-time barista + full-time student. Non-smoker. Rare alcohol.",
        "prior_visits": [
            {"date": "2023-12-02", "type": "PCP", "facility": "East Austin Family Medicine",
             "chief_complaint": "Thyroid follow-up", "disposition": "routine",
             "note": "TSH 2.4 on 75 mcg. Stable. Continue current dose. Annual labs."},
        ],
    },
]


def _to_ddb(obj):
    from decimal import Decimal
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_ddb(v) for v in obj]
    return obj


def seed() -> None:
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    for r in RECORDS:
        item = _to_ddb(dict(r))
        table.put_item(Item=item)
        print(f"  [ok]    {item['mrn']:16} {item['name']}")


def main() -> None:
    print("EHR table:")
    ensure_table()
    print("\nSeeding records:")
    seed()
    print(f"\n{len(RECORDS)} records in {TABLE}. Search via GSI: hospital_name-index (hospital_id + name_lower).")


if __name__ == "__main__":
    main()
