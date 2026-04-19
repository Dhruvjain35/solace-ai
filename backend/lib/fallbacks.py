"""Hardcoded fallback comfort protocols per ESI level. Used if Claude fails to return JSON."""
from __future__ import annotations

FALLBACK_PROTOCOLS: dict[int, list[dict]] = {
    1: [
        {
            "title": "Stay Still",
            "instruction": "Do not get up or move. The medical team is being prepared for you right now. Help is coming.",
            "icon": "🙏",
        },
        {
            "title": "Breathe",
            "instruction": "Slow, steady breaths. In through your nose, out through your mouth. Focus only on your breath.",
            "icon": "🌬️",
        },
    ],
    2: [
        {
            "title": "Stay Seated",
            "instruction": "Remain in your seat. A clinician has been notified of your priority level. Avoid walking around.",
            "icon": "🪑",
        },
        {
            "title": "Slow Breathing",
            "instruction": "Breathe in for 4 counts, hold for 2, out for 6. Repeat 10 times to ease tension.",
            "icon": "🌬️",
        },
    ],
    3: [
        {
            "title": "Find a Comfortable Position",
            "instruction": "Sit upright with your back supported. If possible, keep both feet flat on the floor.",
            "icon": "🪑",
        },
        {
            "title": "Breathe Slowly",
            "instruction": "Inhale for 4 counts through your nose, exhale for 6 through your mouth. This calms the nervous system.",
            "icon": "🌬️",
        },
        {
            "title": "Sip Water",
            "instruction": "If you are able to swallow safely, take small sips of water. Hydration helps most conditions.",
            "icon": "💧",
        },
    ],
    4: [
        {
            "title": "Rest and Elevate",
            "instruction": "If a limb is injured or swollen, elevate it gently above heart level when seated.",
            "icon": "🦵",
        },
        {
            "title": "Ice or Heat as Needed",
            "instruction": "For minor swelling, a cool cloth can reduce it. For muscle stiffness, gentle warmth helps.",
            "icon": "🧊",
        },
        {
            "title": "Stay Hydrated",
            "instruction": "Sip water slowly. Avoid caffeine while waiting.",
            "icon": "💧",
        },
    ],
    5: [
        {
            "title": "Rest Comfortably",
            "instruction": "Find a comfortable seated position. The wait may be longer as more urgent patients are seen first.",
            "icon": "🪑",
        },
        {
            "title": "Stay Hydrated",
            "instruction": "Sip water. Avoid food unless a nurse has cleared you.",
            "icon": "💧",
        },
    ],
}


ESI_LABELS: dict[int, str] = {
    1: "Critical",
    2: "Emergent",
    3: "Urgent",
    4: "Less Urgent",
    5: "Non-Urgent",
}


GENERIC_PATIENT_EXPLANATION: dict[int, str] = {
    1: "Your condition needs immediate attention. The medical team is being prepared for you right now.",
    2: "Your condition is serious and you are a high priority. A clinician will see you very soon. Please stay seated.",
    3: "Your condition is serious but stable. A clinician will see you within about 30-60 minutes.",
    4: "Your condition is not immediately urgent. You will be seen as soon as more serious cases are handled.",
    5: "Your condition is minor. There may be a longer wait as more urgent patients are seen first.",
}
