"""Claude-generated patient comfort protocol. Returns exactly 3 action cards.

Patient-facing output: numbered, plain-text cards. No emoji is ever emitted —
emoji from the Claude response or from lib.fallbacks is stripped here so the
clinical UI stays text-only (constitution QUAL-004).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from lib.fallbacks import FALLBACK_PROTOCOLS
from lib.medical_format import format_medical_info

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

# Patient-facing copy limits.
_MAX_TITLE_LEN = 40
_MAX_INSTRUCTION_LEN = 160

# Emoji / pictographic ranges to strip from any patient-facing string.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoji
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators
    "\U00002B00-\U00002BFF"  # arrows / misc
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "]+"
)


def _strip_emoji(text: str) -> str:
    """Remove emoji/pictographs and collapse the whitespace they leave behind."""
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", text or "")).strip()


def _sanitize_cards(cards: list[dict]) -> list[dict]:
    """Strip emoji, drop the icon field, clamp lengths. Returns title/instruction only."""
    out: list[dict] = []
    for item in cards if isinstance(cards, list) else []:
        if not isinstance(item, dict):
            continue
        title = _strip_emoji(str(item.get("title", "")))[:_MAX_TITLE_LEN].strip()
        instruction = _strip_emoji(str(item.get("instruction", "")))[:_MAX_INSTRUCTION_LEN].strip()
        if title and instruction:
            out.append({"title": title, "instruction": instruction})
    return out


# Per-language fallback cards (exactly 3) used when lib.fallbacks cannot supply 3
# sanitized cards. lib.fallbacks is English-only and not always 3 entries.
_FALLBACK_BY_LANG: dict[str, dict[int, list[dict]]] = {
    "es": {
        1: [
            {"title": "Quedese quieto", "instruction": "No se levante ni se mueva. El equipo medico se esta preparando para usted. La ayuda viene en camino."},
            {"title": "Respire", "instruction": "Respiraciones lentas y constantes. Inhale por la nariz, exhale por la boca. Concentrese solo en su respiracion."},
            {"title": "Mantenga la calma", "instruction": "Es una prioridad alta. Un miembro del personal lo atendera muy pronto. Permanezca sentado."},
        ],
        2: [
            {"title": "Permanezca sentado", "instruction": "Quedese en su asiento. Un clinico ya conoce su nivel de prioridad. Evite caminar."},
            {"title": "Respiracion lenta", "instruction": "Inhale 4 tiempos, sostenga 2, exhale 6. Repita 10 veces para aliviar la tension."},
            {"title": "Mantenga la calma", "instruction": "La ayuda esta cerca. Concentrese en respiraciones lentas mientras espera al clinico."},
        ],
        3: [
            {"title": "Posicion comoda", "instruction": "Sientese erguido con la espalda apoyada. Si puede, mantenga ambos pies planos en el suelo."},
            {"title": "Respire despacio", "instruction": "Inhale 4 tiempos por la nariz, exhale 6 por la boca. Esto calma el sistema nervioso."},
            {"title": "Tome agua", "instruction": "Si puede tragar con seguridad, tome pequenos sorbos de agua. La hidratacion ayuda."},
        ],
        4: [
            {"title": "Descanse y eleve", "instruction": "Si una extremidad esta lesionada o hinchada, elevela suavemente por encima del corazon al sentarse."},
            {"title": "Frio o calor", "instruction": "Para hinchazon leve, un pano fresco ayuda. Para rigidez muscular, un calor suave alivia."},
            {"title": "Mantengase hidratado", "instruction": "Tome agua despacio. Evite la cafeina mientras espera."},
        ],
        5: [
            {"title": "Descanse comodo", "instruction": "Busque una posicion sentada comoda. La espera puede ser mas larga; primero se atienden casos urgentes."},
            {"title": "Mantengase hidratado", "instruction": "Tome agua. Evite comer hasta que una enfermera lo autorice."},
            {"title": "Mantenga la calma", "instruction": "Respire despacio y descanse. El personal lo atendera tan pronto como sea posible."},
        ],
    },
}

# Extra English cards, by ESI level, used to pad a short lib.fallbacks list to 3.
_EN_PADDING: dict[int, list[dict]] = {
    1: [{"title": "Stay Calm", "instruction": "You are a high priority. A staff member will reach you very soon. Please remain seated."}],
    2: [{"title": "Stay Calm", "instruction": "Help is close. Focus on slow breathing while you wait for the clinician."}],
    3: [{"title": "Stay Calm", "instruction": "Breathe slowly and rest. A clinician will be with you as soon as possible."}],
    4: [{"title": "Stay Calm", "instruction": "Rest while you wait. Let a nurse know if your symptoms get worse."}],
    5: [{"title": "Stay Calm", "instruction": "Breathe slowly and rest. Staff will reach you as soon as possible."}],
}


def _fallback(esi_level: int, language: str) -> list[dict]:
    """Return exactly 3 sanitized fallback cards for the ESI level and language."""
    level = esi_level if esi_level in FALLBACK_PROTOCOLS else 3
    lang = (language or "en").lower().split("-")[0]

    lang_table = _FALLBACK_BY_LANG.get(lang)
    if lang_table:
        cards = _sanitize_cards(lang_table.get(level, lang_table[3]))
        if len(cards) >= 3:
            return cards[:3]

    cards = _sanitize_cards(FALLBACK_PROTOCOLS.get(level, FALLBACK_PROTOCOLS[3]))
    if len(cards) < 3:
        cards = cards + _sanitize_cards(_EN_PADDING.get(level, _EN_PADDING[3]))
    return cards[:3]


_SYSTEM = """You are Solace, a compassionate ER companion. Generate comfort guidance for a waiting ER patient.

Rules:
- ESI 1-2: Focus on staying calm and still. NO physical exercises. Reassure help is coming.
- ESI 3: Gentle positional comfort, breathing, pain management.
- ESI 4-5: Active comfort — elevation, ice/heat, reasonable mobility.
- Return EXACTLY 3 actions (not 2, not 4). Each has: title (1-3 words), instruction (1 short sentence, <25 words).
- Plain text only. Do NOT use emoji, symbols, or markdown in the title or instruction.
- Tailor to the patient's symptoms and known allergies/medications/conditions.
- NEVER suggest something that could interact with their meds or conditions.
- Respond ONLY in language code: {language}.
- Return JSON array only. No preamble, no markdown fence.

JSON schema:
[{{"title": "...", "instruction": "..."}}]"""


def generate(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    language: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
) -> list[dict]:
    if not claude.available():
        return _fallback(esi_level, language)
    try:
        user_parts = [
            f'Patient transcript:\n"""\n{transcript.strip()}\n"""',
            f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}",
            f"ESI level: {esi_level}",
        ]
        if medical_info:
            user_parts.append(f"Medical history: {format_medical_info(medical_info)}")
        if followup_qa:
            from services.followups import format_qa_for_prompts

            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up answers:\n{qa}")
        user_parts.append("Return the JSON array of exactly 3 actions now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM.format(language=language),
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="comfort_protocol",
        )
        raw = "".join(b.text for b in resp.content)
        parsed = _parse(raw)
        if parsed:
            return parsed
        log.warning("Comfort protocol parse failed; using fallback (len=%d, content redacted)", len(raw))
    except Exception as e:
        log.exception("Comfort protocol generation failed: %s", e)
    return _fallback(esi_level, language)


def _parse(raw: str) -> list[dict]:
    """Parse the Claude JSON array into exactly 3 sanitized, emoji-free cards.

    Returns [] if fewer than 3 valid cards are produced so the caller can fall
    back to a guaranteed 3-card protocol.
    """
    arr = json_extract.extract_array(raw)
    if not arr:
        return []
    cleaned = _sanitize_cards(arr)
    if len(cleaned) < 3:
        return []
    return cleaned[:3]
