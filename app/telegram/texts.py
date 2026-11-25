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
        "chat_divider": "━━━━━━━━━━━━\n{icon} <b>{name}</b>\n━━━━━━━━━━━━",
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
        "group_ready": "You're in the group <b>{name}</b>.",
        "group_resumed": "Back in the group <b>{name}</b>.",
        "new_chat_in_group": "Use /newgroup to create another group, or pick a character to chat with.",
        "cmd_newgroup": "Create a group",
        "proactive_status_on": "Characters may message you first: <b>on</b>.\nTurn off: /proactive off",
        "proactive_status_off": "Characters may message you first: <b>off</b>.\nTurn on: /proactive on",
        "proactive_on": "Okay, characters may now message you first from time to time (never at night).",
        "proactive_off": "Okay, characters will only answer when you write.",
        "proactive_unavailable": "This feature is not active yet.",
        "cmd_proactive": "Let characters message first (on/off)",
        "cmd_credits": "Your credits",
        "credits_off": "Credits are not active right now.",
        "credits_balance": (
            "💳 You have <b>{credits}</b> credits.\n"
            "A message costs {message}, a group message {group_message}, "
            "creating a group {group_create}."
        ),
        "credits_subscribed": (
            "⭐ Your subscription is active until <b>{until}</b>. "
            "Messages and groups are included. Extra credits: {credits}."
        ),
        "credits_empty": (
            "Your credits are used up. To keep chatting you need credits or a "
            "subscription. Buying them will be available here soon."
        ),
        "daily_cap": "You reached today's message limit. Please come back tomorrow.",
        "group_needs_credits": (
            "Creating a group costs {cost} credits (free with a subscription). "
            "You have {credits}."
        ),
        "btn_delete": "🗑 Delete {name}",
        "btn_delete_yes": "🗑 Yes, delete",
        "delete_confirm": (
            "<b>Delete {name}?</b>\n\nThis permanently removes:\n"
            "• Chats with {name}: {chats}\n"
            "• Things {name} remembers about you: {memories}\n"
            "• Groups with {name}: {groups} ({name} leaves them; groups left with "
            "fewer than 2 characters are deleted: {groups_deleted})\n\n"
            "This cannot be undone. You can always start fresh with {name} later."
        ),
        "delete_done": (
            "<b>{name}</b> was deleted.\nChats: {chats} · Memories: {memories} · "
            "Groups left: {groups} (deleted: {groups_deleted})"
        ),
        "delete_cancelled": "Nothing was deleted.",
        "delete_nothing": "There is nothing to delete for {name}.",
        "delete_pick": "Open a chat with a character first, then use /delete.",
        "cmd_delete": "Delete the current character",
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
        "chat_divider": "━━━━━━━━━━━━\n{icon} <b>{name}</b>\n━━━━━━━━━━━━",
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
        "group_ready": "<b>{name}</b> grubundasın.",
        "group_resumed": "<b>{name}</b> grubuna döndün.",
        "new_chat_in_group": "Başka bir grup için /newgroup yaz, ya da sohbet etmek için bir karakter seç.",
        "cmd_newgroup": "Grup oluştur",
        "proactive_status_on": "Karakterlerin sana ilk yazması: <b>açık</b>.\nKapatmak için: /proactive off",
        "proactive_status_off": "Karakterlerin sana ilk yazması: <b>kapalı</b>.\nAçmak için: /proactive on",
        "proactive_on": "Tamam, karakterler ara sıra sana ilk yazabilir (geceleri asla).",
        "proactive_off": "Tamam, karakterler sadece sen yazınca cevap verecek.",
        "proactive_unavailable": "Bu özellik henüz aktif değil.",
        "cmd_proactive": "Karakterler ilk yazsın (açık/kapalı)",
        "cmd_credits": "Kredilerin",
        "credits_off": "Kredi sistemi şu an aktif değil.",
        "credits_balance": (
            "💳 <b>{credits}</b> kredin var.\n"
            "Bir mesaj {message}, grup mesajı {group_message}, "
            "grup kurmak {group_create} kredi."
        ),
        "credits_subscribed": (
            "⭐ Aboneliğin <b>{until}</b> tarihine kadar aktif. "
            "Mesajlar ve grup kurma dahil. Ekstra kredi: {credits}."
        ),
        "credits_empty": (
            "Kredin bitti. Sohbete devam etmek için kredi ya da abonelik gerekiyor. "
            "Satın alma çok yakında burada olacak."
        ),
        "daily_cap": "Bugünkü mesaj sınırına ulaştın. Lütfen yarın tekrar gel.",
        "group_needs_credits": (
            "Grup kurmak {cost} kredi (abonelikte ücretsiz). Senin {credits} kredin var."
        ),
        "btn_delete": "🗑 {name} kişisini sil",
        "btn_delete_yes": "🗑 Evet, sil",
        "delete_confirm": (
            "<b>{name} silinsin mi?</b>\n\nKalıcı olarak silinecekler:\n"
            "• {name} ile sohbetler: {chats}\n"
            "• {name} kişisinin senin hakkında hatırladıkları: {memories}\n"
            "• {name} olan gruplar: {groups} ({name} gruplardan çıkar; 2'den az "
            "karakteri kalan gruplar silinir: {groups_deleted})\n\n"
            "Bu geri alınamaz. {name} ile daha sonra baştan başlayabilirsin."
        ),
        "delete_done": (
            "<b>{name}</b> silindi.\nSohbet: {chats} · Hafıza: {memories} · "
            "Çıkarıldığı grup: {groups} (silinen: {groups_deleted})"
        ),
        "delete_cancelled": "Hiçbir şey silinmedi.",
        "delete_nothing": "{name} için silinecek bir şey yok.",
        "delete_pick": "Önce bir karakterle sohbet aç, sonra /delete kullan.",
        "cmd_delete": "Mevcut karakteri sil",
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
