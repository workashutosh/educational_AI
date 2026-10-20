"""
Multilingual support for chat: answer in the student's language and, when the
embedding model is English-only, translate the question for retrieval.

To retrieve natively in Indian languages instead, set
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
(same 384 dims) + EMBEDDING_MULTILINGUAL=True and run `manage.py reembed_chunks`.
"""
from __future__ import annotations

import logging
import unicodedata

from django.conf import settings

from .llm_provider import chat_completion

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
    "ur": "Urdu",
    "as": "Assamese",
}

NOT_FOUND_EN = "I couldn't find that in the indexed notes."


def normalize_language(code: str | None) -> str:
    code = (code or "").strip().lower()
    if code in SUPPORTED_LANGUAGES:
        return code
    for key, name in SUPPORTED_LANGUAGES.items():
        if code == name.lower():
            return key
    return "en"


def language_name(code: str | None) -> str:
    return SUPPORTED_LANGUAGES.get(normalize_language(code), "English")


def answer_instruction(code: str | None) -> str:
    """Extra system-prompt text so the model replies in the chosen language."""
    code = normalize_language(code)
    if code == "en":
        return ""
    name = SUPPORTED_LANGUAGES[code]
    return (
        f"\n\nLANGUAGE: Write the whole answer in {name} (native script). Keep formulas, "
        "LaTeX, chemical equations, and standard technical terms as they are (you may add "
        f"the {name} term in brackets). Citations like [1] stay unchanged. If the excerpts do "
        f'not address the question, reply exactly in English: "{NOT_FOUND_EN}"'
    )


def mostly_non_latin(text: str) -> bool:
    letters = [ch for ch in text or "" if ch.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for ch in letters if "LATIN" not in unicodedata.name(ch, "LATIN"))
    return non_latin / len(letters) > 0.3


def retrieval_query_in_english(question: str) -> str:
    """Translate a non-English question for the English-only embedding index."""
    if getattr(settings, "EMBEDDING_MULTILINGUAL", False) or not mostly_non_latin(question):
        return question
    try:
        translated = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "Translate the student's question into English for a search engine. "
                        "Output only the English question, nothing else."
                    ),
                },
                {"role": "user", "content": question[:1500]},
            ],
            temperature=0,
            max_tokens=200,
            timeout=30,
        )
        return translated.strip().strip('"') or question
    except Exception:
        logger.warning("retrieval translation failed; using original text", exc_info=True)
        return question


def translate_text(text: str, target: str) -> str:
    name = language_name(target)
    return chat_completion(
        [
            {
                "role": "system",
                "content": (
                    f"Translate the text into {name}. Preserve markdown, LaTeX ($...$), "
                    "numbers, and citations like [1]. Output only the translation."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        max_tokens=3000,
        timeout=90,
    )
