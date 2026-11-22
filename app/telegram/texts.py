"""User-facing Telegram texts (Turkish and English).

Everything here is sent with parse_mode=HTML, so dynamic values must be
escaped by the caller (see handlers). Texts themselves may contain tags.
"""

DEFAULT_LANGUAGE = "en"

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "Hi{name}! Welcome to Peligrosa.\n"
            "Pick a character to get to know them."
        ),
        "gallery_title": "<b>Characters</b> ({page}/{total})",
        "gallery_empty": "There are no characters available right now. Please check back soon.",
        "card_open": "Chat with {name}",
        "card_back": "‹ Back",
        "page_previous": "‹ Previous",
        "page_next": "Next ›",
        "chat_soon": "Chatting is coming very soon!",
        "plain_text": "Chatting is coming very soon! For now, use /characters to browse the characters.",
        "character_missing": "That character is not available anymore.",
        "error": "Something went wrong. Please try again.",
    },
    "tr": {
        "welcome": (
            "Merhaba{name}! Peligrosa'ya hoş geldin.\n"
            "Tanışmak için bir karakter seç."
        ),
        "gallery_title": "<b>Karakterler</b> ({page}/{total})",
        "gallery_empty": "Şu anda gösterilecek karakter yok. Lütfen biraz sonra tekrar bak.",
        "card_open": "{name} ile sohbet et",
        "card_back": "‹ Geri",
        "page_previous": "‹ Önceki",
        "page_next": "Sonraki ›",
        "chat_soon": "Sohbet çok yakında geliyor!",
        "plain_text": "Sohbet çok yakında geliyor! Şimdilik karakterlere göz atmak için /characters yaz.",
        "character_missing": "Bu karakter artık mevcut değil.",
        "error": "Bir şeyler ters gitti. Lütfen tekrar dene.",
    },
}


def resolve_language(language_code: str | None) -> str:
    return language_code if language_code in TEXTS else DEFAULT_LANGUAGE


def t(language_code: str | None, key: str, **values: object) -> str:
    text = TEXTS[resolve_language(language_code)][key]
    return text.format(**values) if values else text
