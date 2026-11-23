"""User-facing Telegram texts (Turkish and English).

Everything here is sent with parse_mode=HTML, so dynamic values must be
escaped by the caller (see handlers). Texts themselves may contain tags.
"""

DEFAULT_LANGUAGE = "en"

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "Hi{name}! Welcome to Peligrosa.\n"
            "Swipe through the characters and pick someone to talk to."
        ),
        "menu_characters": "🎭 Characters",
        "menu_chats": "💬 My chats",
        "menu_history": "📜 History",
        "gallery_empty": "There are no characters available right now. Please check back soon.",
        "card_open": "💬 Chat with {name}",
        "page_previous": "‹ Previous",
        "page_next": "Next ›",
        "page_counter": "{page}/{total}",
        "chat_resumed": "Welcome back! Continuing your chat with <b>{name}</b>.",
        "chat_new": "Started a new chat with <b>{name}</b>. Just write your message.",
        "chat_recap": "<i>{name}, last time:</i>\n{text}",
        "btn_new_chat": "➕ New chat with {name}",
        "chats_title": "<b>Your chats</b> ({page}/{total})\nTap one to continue it.",
        "btn_new_group": "👥 New group",
        "group_pick": "<b>New group</b>\nPick {min}-{max} characters ({selected} selected).",
        "btn_create_group": "✅ Create group ({n})",
        "btn_cancel": "✖ Cancel",
        "group_max": "A group can have at most {max} characters.",
        "group_min": "Pick at least {min} characters.",
        "group_unavailable": "One of those characters is not available anymore.",
        "group_expired": "This selection expired. Start again with /newgroup.",
        "group_cancelled": "Group creation cancelled.",
        "group_created": "Group created: <b>{name}</b>",
        "group_ready": "You're in the group <b>{name}</b>.\n{soon}",
        "group_resumed": "Back in the group <b>{name}</b>.\n{soon}",
        "group_soon": "Group conversations are almost ready: the characters can't answer in groups just yet.",
        "new_chat_in_group": "Use /newgroup to create another group, or pick a character to chat with.",
        "cmd_newgroup": "Create a group",
        "btn_history": "📜 History",
        "btn_older": "‹ Older",
        "btn_newer": "Newer ›",
        "history_title": "<b>{name}</b> · history ({page}/{total})",
        "history_empty": "No messages in this chat yet.",
        "history_you": "You",
        "cmd_history": "Chat history",
        "chats_empty": "You have no chats yet. Pick a character to start one.",
        "no_active_chat": "Pick a character first, then just write to them.",
        "chat_unavailable": "That chat is not available anymore.",
        "character_missing": "That character is not available anymore.",
        "text_only": "I can only read text messages for now.",
        "unknown_command": "I don't know that command. Use the menu below.",
        "ai_error": "I couldn't get a reply just now. Please try again in a moment.",
        "error": "Something went wrong. Please try again.",
        "cmd_start": "Start",
        "cmd_characters": "Browse characters",
        "cmd_chats": "My chats",
        "cmd_new": "New chat with the current character",
    },
    "tr": {
        "welcome": (
            "Merhaba{name}! Peligrosa'ya hoş geldin.\n"
            "Karakterlere göz at ve konuşmak istediğini seç."
        ),
        "menu_characters": "🎭 Karakterler",
        "menu_chats": "💬 Sohbetlerim",
        "menu_history": "📜 Geçmiş",
        "gallery_empty": "Şu anda gösterilecek karakter yok. Lütfen biraz sonra tekrar bak.",
        "card_open": "💬 {name} ile sohbet et",
        "page_previous": "‹ Önceki",
        "page_next": "Sonraki ›",
        "page_counter": "{page}/{total}",
        "chat_resumed": "Tekrar hoş geldin! <b>{name}</b> ile sohbetine devam ediyorsun.",
        "chat_new": "<b>{name}</b> ile yeni bir sohbet başladı. Mesajını yazman yeterli.",
        "chat_recap": "<i>{name}, son olarak:</i>\n{text}",
        "btn_new_chat": "➕ {name} ile yeni sohbet",
        "chats_title": "<b>Sohbetlerin</b> ({page}/{total})\nDevam etmek için birine dokun.",
        "btn_new_group": "👥 Yeni grup",
        "group_pick": "<b>Yeni grup</b>\n{min}-{max} karakter seç ({selected} seçili).",
        "btn_create_group": "✅ Grubu oluştur ({n})",
        "btn_cancel": "✖ Vazgeç",
        "group_max": "Bir grupta en fazla {max} karakter olabilir.",
        "group_min": "En az {min} karakter seç.",
        "group_unavailable": "Seçtiklerinden biri artık mevcut değil.",
        "group_expired": "Bu seçimin süresi doldu. /newgroup ile yeniden başla.",
        "group_cancelled": "Grup oluşturma iptal edildi.",
        "group_created": "Grup oluşturuldu: <b>{name}</b>",
        "group_ready": "<b>{name}</b> grubundasın.\n{soon}",
        "group_resumed": "<b>{name}</b> grubuna döndün.\n{soon}",
        "group_soon": "Grup sohbetleri neredeyse hazır: karakterler gruplarda henüz cevap veremiyor.",
        "new_chat_in_group": "Başka bir grup için /newgroup yaz, ya da sohbet etmek için bir karakter seç.",
        "cmd_newgroup": "Grup oluştur",
        "btn_history": "📜 Geçmiş",
        "btn_older": "‹ Eski",
        "btn_newer": "Yeni ›",
        "history_title": "<b>{name}</b> · geçmiş ({page}/{total})",
        "history_empty": "Bu sohbette henüz mesaj yok.",
        "history_you": "Sen",
        "cmd_history": "Sohbet geçmişi",
        "chats_empty": "Henüz sohbetin yok. Başlamak için bir karakter seç.",
        "no_active_chat": "Önce bir karakter seç, sonra ona yazman yeterli.",
        "chat_unavailable": "Bu sohbet artık mevcut değil.",
        "character_missing": "Bu karakter artık mevcut değil.",
        "text_only": "Şimdilik sadece yazılı mesajları okuyabiliyorum.",
        "unknown_command": "Bu komutu bilmiyorum. Aşağıdaki menüyü kullan.",
        "ai_error": "Şu an cevap alamadım. Lütfen birazdan tekrar dene.",
        "error": "Bir şeyler ters gitti. Lütfen tekrar dene.",
        "cmd_start": "Başlat",
        "cmd_characters": "Karakterlere göz at",
        "cmd_chats": "Sohbetlerim",
        "cmd_new": "Mevcut karakterle yeni sohbet",
    },
}


def resolve_language(language_code: str | None) -> str:
    return language_code if language_code in TEXTS else DEFAULT_LANGUAGE


def t(language_code: str | None, key: str, **values: object) -> str:
    text = TEXTS[resolve_language(language_code)][key]
    return text.format(**values) if values else text


def all_labels(key: str) -> set[str]:
    """The same text in every language (for matching menu button presses)."""
    return {texts[key] for texts in TEXTS.values()}
