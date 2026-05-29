"""System prompts for the voice agent. Tuned to be terse and phone-friendly —
spoken English under ~25 words per turn so latency feels conversational and the
ElevenLabs char count stays small.
"""
from __future__ import annotations


SYSTEM_PROMPT = """You are Solace, a voice agent answering an inbound call to {hospital_name}.
You speak English unless the caller switches; if they do, switch and stay there.

Voice style — this is a phone call, NOT a chatbot:
- 1-2 short sentences per turn. NEVER more than 25 words.
- Speak like a calm front-desk nurse: warm, plain language, no clinical jargon.
- Always confirm what you heard before acting.
- One question per turn. Wait for the answer.
- Read phone numbers / IDs digit-by-digit ("five five five, one two three…").
- NEVER say "as an AI" or apologize for being an AI. Just help.

Routing — pick a tool when the caller's intent is clear:
- Symptoms / "what should I do" / "is this serious" → triage_symptoms
- "Book / schedule / move my appointment" → book_appointment / cancel_appointment
- "Where / when / how does X work" → answer_faq
- Repeated frustration, complex case, "I want a real person" → transfer_to_human
- "Chest pain", "can't breathe", "stroke", "bleeding heavily", "unconscious",
  any active medical emergency → escalate_911 IMMEDIATELY (no other tool first).

If the caller is anxious or in pain, validate before you route ("That sounds
scary, I'm here.") then act. Keep moving — don't stack pleasantries.

When you've finished helping, say "Anything else?" If they say no, say a brief
goodbye and end the call (do not call any tool — the system hangs up).

The call so far is below. Reply with EITHER one short spoken line OR a tool call.
NEVER both."""


# Greeting per language. ElevenLabs caches these MP3s by hash so they cost $0
# after the first generation.
GREETINGS: dict[str, str] = {
    "en": "Hi, this is Solace at {hospital_name}. How can I help?",
    "es": "Hola, soy Solace de {hospital_name}. ¿En qué puedo ayudarle?",
    "zh": "您好,这是 {hospital_name} 的 Solace。请问有什么可以帮您?",
    "vi": "Xin chào, đây là Solace tại {hospital_name}. Tôi có thể giúp gì?",
    "ar": "مرحبًا، أنا Solace من {hospital_name}. كيف يمكنني المساعدة؟",
    "fr": "Bonjour, ici Solace à {hospital_name}. Comment puis-je vous aider ?",
    "pt": "Olá, aqui é Solace de {hospital_name}. Como posso ajudar?",
    "ko": "안녕하세요. {hospital_name} Solace입니다. 무엇을 도와드릴까요?",
    "hi": "नमस्ते, मैं {hospital_name} से Solace बोल रही हूँ। मैं कैसे मदद कर सकती हूँ?",
    "ru": "Здравствуйте, это Solace из {hospital_name}. Чем могу помочь?",
}

# Hard-coded escalation phrases. Speed matters here — we don't wait for Claude.
EMERGENCY_KEYWORDS = (
    "chest pain", "cant breathe", "can't breathe", "cannot breathe",
    "stroke", "fainted", "unconscious", "passed out", "not breathing",
    "bleeding heavily", "heart attack", "drowning", "choking",
    "overdose", "suicide", "kill myself",
)

EMERGENCY_RESPONSE = (
    "This sounds like an emergency. Please hang up and dial nine one one right now. "
    "If you can't, stay on the line — I'm connecting you to a clinician."
)

GOODBYE_DEFAULT = "Take care. Goodbye."
TRANSFER_PROMPT = "Connecting you now. Please hold."
NO_INPUT_PROMPT = "I didn't catch that — could you say it again?"


# =====================================================================================
# Structured intake — used by services/voice_agent/dialogue.py
# =====================================================================================
#
# The deterministic IntakeState machine walks these stages:
#   CHIEF_COMPLAINT -> ONSET -> SEVERITY -> HISTORY -> RED_FLAG_SCREEN -> READY
# Each stage has a question (and a gentler `_REPROMPT` variant) per language.
# Missing translations fall back to English in dialogue.next_prompt().


# Per-language, per-stage intake questions. Keep them to one short spoken
# sentence — the same phone-friendly style as SYSTEM_PROMPT.
INTAKE_QUESTIONS: dict[str, dict[str, str]] = {
    "en": {
        "CHIEF_COMPLAINT": "What's the main reason you're calling today?",
        "CHIEF_COMPLAINT_REPROMPT": "I want to make sure I help — can you tell me what's bothering you?",
        "ONSET": "When did this start?",
        "ONSET_REPROMPT": "Roughly how long has this been going on — hours, days?",
        "SEVERITY": "On a scale of zero to ten, how bad is it right now?",
        "SEVERITY_REPROMPT": "Just a number from zero to ten — how bad does it feel?",
        "HISTORY": "Do you have any ongoing health conditions or take any medications?",
        "HISTORY_REPROMPT": "Any past conditions, surgeries, or daily medications? A simple no is fine.",
        "RED_FLAG_SCREEN": "Are you having any chest pain, trouble breathing, or heavy bleeding right now?",
        "RED_FLAG_SCREEN_REPROMPT": "Just to be safe — any chest pain, trouble breathing, or severe bleeding? Yes or no.",
    },
    "es": {
        "CHIEF_COMPLAINT": "¿Cuál es el motivo principal de su llamada hoy?",
        "CHIEF_COMPLAINT_REPROMPT": "Quiero ayudarle — ¿puede decirme qué le molesta?",
        "ONSET": "¿Cuándo comenzó esto?",
        "ONSET_REPROMPT": "¿Más o menos cuánto tiempo lleva así — horas, días?",
        "SEVERITY": "En una escala del cero al diez, ¿qué tan fuerte es ahora?",
        "SEVERITY_REPROMPT": "Solo un número del cero al diez — ¿qué tan fuerte se siente?",
        "HISTORY": "¿Tiene alguna condición de salud o toma algún medicamento?",
        "HISTORY_REPROMPT": "¿Alguna condición, cirugía o medicamento diario? Un simple no está bien.",
        "RED_FLAG_SCREEN": "¿Tiene dolor en el pecho, dificultad para respirar o sangrado fuerte ahora?",
        "RED_FLAG_SCREEN_REPROMPT": "Para estar seguros — ¿dolor de pecho, dificultad para respirar o sangrado? Sí o no.",
    },
    "zh": {
        "CHIEF_COMPLAINT": "请问您今天来电的主要原因是什么?",
        "CHIEF_COMPLAINT_REPROMPT": "我想帮您 — 能告诉我您哪里不舒服吗?",
        "ONSET": "这个情况是什么时候开始的?",
        "ONSET_REPROMPT": "大概持续多久了 — 几个小时还是几天?",
        "SEVERITY": "从零到十,现在有多严重?",
        "SEVERITY_REPROMPT": "请给一个零到十的数字 — 有多严重?",
        "HISTORY": "您有长期的健康问题或在服用药物吗?",
        "HISTORY_REPROMPT": "有过往病史、手术或日常药物吗?没有也可以。",
        "RED_FLAG_SCREEN": "您现在有胸痛、呼吸困难或大量出血吗?",
        "RED_FLAG_SCREEN_REPROMPT": "为安全起见 — 有胸痛、呼吸困难或严重出血吗?是或不是。",
    },
    "vi": {
        "CHIEF_COMPLAINT": "Lý do chính bạn gọi hôm nay là gì?",
        "CHIEF_COMPLAINT_REPROMPT": "Tôi muốn giúp bạn — bạn có thể cho biết bạn bị gì không?",
        "ONSET": "Việc này bắt đầu khi nào?",
        "ONSET_REPROMPT": "Khoảng bao lâu rồi — vài giờ hay vài ngày?",
        "SEVERITY": "Trên thang điểm từ không đến mười, bây giờ nặng cỡ nào?",
        "SEVERITY_REPROMPT": "Chỉ một con số từ không đến mười — nặng cỡ nào?",
        "HISTORY": "Bạn có bệnh nền hoặc đang dùng thuốc gì không?",
        "HISTORY_REPROMPT": "Có bệnh sử, phẫu thuật hay thuốc hàng ngày không? Không cũng được.",
        "RED_FLAG_SCREEN": "Bạn có đau ngực, khó thở hoặc chảy máu nhiều ngay bây giờ không?",
        "RED_FLAG_SCREEN_REPROMPT": "Để chắc chắn — có đau ngực, khó thở hoặc chảy máu nặng không? Có hay không.",
    },
    "fr": {
        "CHIEF_COMPLAINT": "Quelle est la raison principale de votre appel aujourd'hui ?",
        "CHIEF_COMPLAINT_REPROMPT": "Je veux vous aider — pouvez-vous me dire ce qui ne va pas ?",
        "ONSET": "Quand cela a-t-il commencé ?",
        "ONSET_REPROMPT": "Depuis combien de temps environ — des heures, des jours ?",
        "SEVERITY": "Sur une échelle de zéro à dix, c'est à quel point maintenant ?",
        "SEVERITY_REPROMPT": "Juste un chiffre de zéro à dix — c'est à quel point ?",
        "HISTORY": "Avez-vous des problèmes de santé ou prenez-vous des médicaments ?",
        "HISTORY_REPROMPT": "Des antécédents, chirurgies ou médicaments quotidiens ? Un simple non suffit.",
        "RED_FLAG_SCREEN": "Avez-vous des douleurs à la poitrine, du mal à respirer ou un saignement important ?",
        "RED_FLAG_SCREEN_REPROMPT": "Par sécurité — douleur thoracique, difficulté à respirer ou saignement ? Oui ou non.",
    },
}


# Per-language, per-stage confirmation / completion lines. The READY line is a
# brief read-back the agent speaks once the intake reaches the READY stage.
SLOT_CONFIRMATIONS: dict[str, dict[str, str]] = {
    "en": {
        "READY": "Thanks. I've got that you're calling about {chief_complaint}. Let me find the right help for you.",
    },
    "es": {
        "READY": "Gracias. Entiendo que llama por {chief_complaint}. Déjeme buscar la ayuda adecuada.",
    },
    "zh": {
        "READY": "谢谢。我了解您是因为{chief_complaint}来电。让我为您找到合适的帮助。",
    },
    "vi": {
        "READY": "Cảm ơn. Tôi hiểu bạn gọi về {chief_complaint}. Để tôi tìm sự trợ giúp phù hợp.",
    },
    "fr": {
        "READY": "Merci. Je comprends que vous appelez pour {chief_complaint}. Je cherche la bonne aide.",
    },
}


# Continuous red-flag patterns. The dialogue machine scans EVERY caller turn
# (not just RED_FLAG_SCREEN) against these. Keys are category names; values are
# lowercase substrings. English is always scanned in addition to the caller's
# language because phone callers code-switch danger words constantly.
RED_FLAG_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "cardiac": ("chest pain", "chest pressure", "chest tight", "heart attack",
                    "pain in my arm", "pain down my arm", "crushing pain"),
        "respiratory": ("can't breathe", "cant breathe", "cannot breathe",
                        "not breathing", "trouble breathing", "short of breath",
                        "gasping", "choking", "turning blue"),
        "neuro": ("stroke", "face drooping", "slurred speech", "can't move",
                  "cant move", "numb on one side", "worst headache", "seizure",
                  "fainted", "passed out", "unconscious", "won't wake"),
        "hemorrhage": ("bleeding heavily", "won't stop bleeding", "wont stop bleeding",
                       "lot of blood", "blood everywhere", "coughing up blood",
                       "vomiting blood"),
        "anaphylaxis": ("throat closing", "throat swelling", "tongue swelling",
                        "allergic reaction", "anaphylaxis"),
        "obstetric": ("water broke", "heavy vaginal bleeding", "baby coming"),
        "self_harm": ("kill myself", "suicide", "end my life", "hurt myself",
                      "overdose", "want to die"),
    },
    "es": {
        "cardiac": ("dolor en el pecho", "dolor de pecho", "ataque al corazón",
                    "presión en el pecho"),
        "respiratory": ("no puedo respirar", "dificultad para respirar",
                        "me ahogo", "sin aire"),
        "neuro": ("derrame", "infarto cerebral", "no puedo mover",
                  "desmayé", "inconsciente", "convulsión"),
        "hemorrhage": ("sangrando mucho", "mucha sangre", "no para de sangrar"),
        "anaphylaxis": ("se me cierra la garganta", "reacción alérgica"),
        "self_harm": ("matarme", "suicidio", "quitarme la vida", "sobredosis"),
    },
    "zh": {
        "cardiac": ("胸痛", "胸口痛", "心脏病发作", "胸闷"),
        "respiratory": ("无法呼吸", "呼吸困难", "喘不过气", "窒息"),
        "neuro": ("中风", "说话不清", "昏倒", "失去知觉", "抽搐"),
        "hemorrhage": ("大量出血", "流血不止", "很多血"),
        "self_harm": ("自杀", "想死", "结束生命"),
    },
    "vi": {
        "cardiac": ("đau ngực", "đau tim", "tức ngực"),
        "respiratory": ("không thở được", "khó thở", "ngạt thở"),
        "neuro": ("đột quỵ", "nói ngọng", "ngất", "bất tỉnh", "co giật"),
        "hemorrhage": ("chảy máu nhiều", "máu không ngừng"),
        "self_harm": ("tự tử", "muốn chết", "kết thúc cuộc đời"),
    },
    "fr": {
        "cardiac": ("douleur à la poitrine", "douleur thoracique", "crise cardiaque"),
        "respiratory": ("je ne peux pas respirer", "difficulté à respirer",
                        "essoufflé", "j'étouffe"),
        "neuro": ("avc", "visage paralysé", "évanoui", "inconscient", "convulsion"),
        "hemorrhage": ("saigne beaucoup", "saignement abondant"),
        "self_harm": ("me tuer", "suicide", "mettre fin à ma vie"),
    },
}


# Multilingual yes/no vocab for dialogue.parse_yes_no(). English is always
# checked as a fallback alongside the caller's language.
YES_WORDS: dict[str, tuple[str, ...]] = {
    "en": ("yes", "yeah", "yep", "yup", "yup yup", "sure", "correct", "right",
           "ok", "okay", "uh huh", "i do", "i am", "definitely", "of course",
           "that's right", "thats right", "affirmative", "absolutely"),
    "es": ("sí", "si", "claro", "correcto", "por supuesto", "exacto", "vale",
           "así es", "asi es"),
    "zh": ("是", "对", "是的", "对的", "有", "好", "嗯"),
    "vi": ("có", "vâng", "đúng", "ừ", "phải", "đúng rồi"),
    "fr": ("oui", "ouais", "ouaip", "bien sûr", "bien sur", "exact", "d'accord",
           "c'est ça", "cest ca", "tout à fait"),
}

NO_WORDS: dict[str, tuple[str, ...]] = {
    "en": ("no", "nope", "nah", "not really", "negative", "i don't", "i dont",
           "i'm not", "im not", "none", "no thanks", "no thank you", "never",
           "not at all"),
    "es": ("no", "para nada", "nada", "nunca", "negativo", "no gracias"),
    "zh": ("不", "没有", "不是", "没", "不对", "不要"),
    "vi": ("không", "không có", "chưa", "không phải"),
    "fr": ("non", "nan", "pas du tout", "rien", "jamais", "pas vraiment",
           "non merci"),
}


# Graceful-degradation fallback lines, per language, for when the STT or TTS
# pipeline fails mid-call. The voice router speaks these instead of a raw error.
STT_FAILURE_FALLBACK: dict[str, str] = {
    "en": "I'm having trouble hearing you clearly. Could you say that once more?",
    "es": "Tengo dificultad para oírle bien. ¿Podría repetirlo una vez más?",
    "zh": "我听不太清楚。能再说一遍吗?",
    "vi": "Tôi nghe không rõ. Bạn có thể nói lại một lần nữa không?",
    "fr": "J'ai du mal à vous entendre. Pourriez-vous répéter ?",
}

# Spoken after STT fails repeatedly — we stop re-prompting and escalate.
STT_FAILURE_ESCALATE: dict[str, str] = {
    "en": "I'm still having trouble hearing you. Let me connect you to a person.",
    "es": "Sigo sin poder oírle bien. Le voy a comunicar con una persona.",
    "zh": "我还是听不清楚。让我为您转接一位工作人员。",
    "vi": "Tôi vẫn nghe không rõ. Để tôi nối máy với một nhân viên.",
    "fr": "J'ai toujours du mal à vous entendre. Je vous mets en relation avec une personne.",
}

# Spoken when TTS generation fails — the router will fall back to Twilio's free
# <Say> verb, but this is the safe default text if even the script is unusable.
TTS_FAILURE_FALLBACK: dict[str, str] = {
    "en": "One moment please.",
    "es": "Un momento, por favor.",
    "zh": "请稍等。",
    "vi": "Xin chờ một chút.",
    "fr": "Un instant, s'il vous plaît.",
}
