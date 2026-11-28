"""User-facing Telegram texts (Turkish and English).

Everything here is sent with parse_mode=HTML, so dynamic values must be
escaped by the caller (see handlers). Texts themselves may contain tags.
"""

DEFAULT_LANGUAGE = "en"

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": (
            "Hi{name}! Welcome to Peligrosa.\n"
            "Swipe through the characters and pick someone to talk to.\n\n"
            "The characters are fictional AI personalities, and this service is for adults (18+). /terms"
        ),
        "menu_characters": "🎭 Characters",
        "menu_chats": "💬 My chats",
        "menu_history": "📜 History",
        "menu_photo": "📷 Request photo",
        "menu_pictures": "🖼 My pictures",
        "menu_art": "🎨 Create art",
        "cmd_art": "Describe a picture and have your character make it",
        "art_ask": "🎨 Describe the picture you want (a reply to this message works).",
        "art_offer": "🎨 {name} will make this for you. It costs {cost} credits. Go ahead?",
        "art_offer_free": "🎨 {name} will make this for you. Go ahead?",
        "art_invalid": "I could not read a description. Try /art again.",
        "img_pick": "📷 Who should send the photo?",
        "art_pick": "🎨 Who should make it?",
        "img_pick_none": "Nobody in this chat can send pictures.",
        "cmd_pictures": "See the pictures you received",
        "pic_empty": "You have no pictures yet. Use the photo button in a chat to ask for one.",
        "pic_caption": "{name} · {date} · {page}/{total}",
        "pic_missing": "This picture is no longer available.",
        "cmd_photo": "Ask your character for a photo",
        "img_offer": "📷 {name} can send you a photo. It costs {cost} credits. Want one?",
        "img_offer_free": "📷 {name} can send you a photo. Want one?",
        "btn_img_yes": "✅ Yes",
        "btn_img_no": "❌ No thanks",
        "img_working": "📷 {name} is picking a photo…",
        "img_expired": "This offer has expired. Ask for a photo again.",
        "img_unavailable": "{name} can't send photos.",
        "img_off": "Photos are not available right now.",
        "img_no_chat": "Pick a character first, then ask for a photo.",
        "img_failed": "The photo could not be made right now. Your credits were returned. Try again in a moment.",
        "img_refused": "{name} can't send that one. Your credits were returned. Try asking for something else.",
        "gallery_empty": "There are no characters available right now. Please check back soon.",
        "card_open": "💬 Chat with {name}",
        "page_previous": "‹ Previous",
        "page_next": "Next ›",
        "page_counter": "{page}/{total}",
        "chat_divider": "━━━━━━━━━━━━\n{icon} <b>{name}</b>\n━━━━━━━━━━━━",
        "chat_resumed": "Welcome back! Continuing your chat with <b>{name}</b>.",
        "chat_new": "Started a new chat with <b>{name}</b>. Just write your message.",
        "ask_name": "What should I call you? Reply to this message with your name.",
        "name_saved": "Nice to meet you, <b>{name}</b>! Pick a character to start.",
        "name_invalid": "Please send just a name (letters, up to 40 characters). Try /name again.",
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
        "cmd_buy": "Buy credits or a subscription",
        "cmd_terms": "Terms of use",
        "cmd_support": "Support",
        "cmd_paysupport": "Help with a payment",
        "btn_buy": "💳 Buy credits",
        "buy_menu": "What would you like to buy? Payment is made with Telegram Stars. By buying you accept /terms.",
        "buy_pack_button": "{credits} credits — {stars} ⭐",
        "buy_sub_button": "⭐ Subscription, {days} days — {stars} ⭐",
        "buy_unavailable": "Nothing is on sale right now.",
        "invoice_pack_title": "{credits} credits",
        "invoice_pack_description": "Chat credits for Peligrosa.",
        "invoice_sub_title": "Subscription ({days} days)",
        "invoice_sub_description": "Up to {cap} messages a day are included for {days} days.",
        "invoice_sub_description_groups": "Up to {cap} messages a day and creating groups are included for {days} days.",
        "precheckout_rejected": "This item is not available any more or its price changed. Please open /buy again.",
        "pay_thanks_pack": "✅ Thank you! You now have <b>{credits}</b> credits.",
        "pay_thanks_sub": "✅ Thank you! Your subscription is active until <b>{until}</b>.",
        "pay_problem": "We received your payment but could not deliver it automatically. Please contact /paysupport and keep this chat.",
        "terms_text": (
            "<b>Terms of use</b>\n"
            "• Credits and subscriptions are digital items paid with Telegram Stars.\n"
            "• Credits are used by sending messages; a failed reply is refunded automatically.\n"
            "• Characters are fictional AI characters. You must be 18 or older.\n"
            "• Your chats may be used to improve the service and to train our models. "
            "You can delete a chat and what its character remembers with /delete. "
            "For any other request about your data, contact support (/support).\n"
            "• Telegram and Telegram support cannot help with purchases made in this bot. Use /paysupport.\n"
            "• Refunds are handled case by case through /paysupport."
        ),
        "support_text": "Need help? Contact {contact}.",
        "paysupport_text": "Problem with a payment? Contact {contact} and include the time and amount of the payment.",
        "support_missing": "Support contact details have not been set yet.",
        "credits_off": "Credits are not active right now.",
        "credits_balance": (
            "💳 You have <b>{credits}</b> credits.\n"
            "A message costs {message}, a group message {group_message}, "
            "creating a group {group_create}."
        ),
        "credits_subscribed": (
            "⭐ Your subscription is active until <b>{until}</b>: up to {cap} messages a day are included. "
            "Extra credits: {credits}."
        ),
        "credits_empty": (
            "Your credits are used up. To keep chatting you need credits or a "
            "subscription."
        ),
        "daily_cap": "You reached today's message limit. Please come back tomorrow.",
        "group_needs_credits": (
            "Creating a group costs {cost} credits (free with a subscription). "
            "You have {credits}. Use /buy to get more."
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
        "cmd_rename": "Rename the current chat",
        "rename_usage": "Send the new name after the command, e.g. <code>/rename Movie night</code>. Use <code>/rename -</code> to remove it.",
        "rename_saved": "Chat renamed: <b>{name}</b>",
        "rename_cleared": "The chat name was removed.",
        "rename_invalid": "That name is not usable. Try a short plain name (up to 40 characters).",
        "cmd_name": "Change your name",
    },
    "tr": {
        "welcome": (
            "Merhaba{name}! Peligrosa'ya hoş geldin.\n"
            "Karakterlere göz at ve konuşmak istediğini seç.\n\n"
            "Karakterler kurgusal yapay zekâ kişilikleridir ve bu hizmet yetişkinler (18+) içindir. /terms"
        ),
        "menu_characters": "🎭 Karakterler",
        "menu_chats": "💬 Sohbetlerim",
        "menu_history": "📜 Geçmiş",
        "menu_photo": "📷 Fotoğraf iste",
        "menu_pictures": "🖼 Galerim",
        "menu_art": "🎨 Resim yaptır",
        "cmd_art": "Bir resmi tarif et, karakterin yapsın",
        "art_ask": "🎨 İstediğin resmi anlat (bu mesaja yanıt vermen yeterli).",
        "art_offer": "🎨 {name} bunu senin için yapacak. Bedeli {cost} kredi. Devam edelim mi?",
        "art_offer_free": "🎨 {name} bunu senin için yapacak. Devam edelim mi?",
        "art_invalid": "Bir tarif okuyamadım. /art ile tekrar dene.",
        "img_pick": "📷 Fotoğrafı kim göndersin?",
        "art_pick": "🎨 Kim yapsın?",
        "img_pick_none": "Bu sohbette resim gönderebilecek kimse yok.",
        "cmd_pictures": "Aldığın fotoğrafları gör",
        "pic_empty": "Henüz fotoğrafın yok. Bir sohbette fotoğraf butonuyla isteyebilirsin.",
        "pic_caption": "{name} · {date} · {page}/{total}",
        "pic_missing": "Bu fotoğraf artık mevcut değil.",
        "cmd_photo": "Karakterinden fotoğraf iste",
        "img_offer": "📷 {name} sana bir fotoğraf gönderebilir. Bedeli {cost} kredi. İster misin?",
        "img_offer_free": "📷 {name} sana bir fotoğraf gönderebilir. İster misin?",
        "btn_img_yes": "✅ Evet",
        "btn_img_no": "❌ Hayır",
        "img_working": "📷 {name} bir fotoğraf seçiyor…",
        "img_expired": "Bu teklifin süresi doldu. Tekrar fotoğraf iste.",
        "img_unavailable": "{name} fotoğraf gönderemiyor.",
        "img_off": "Fotoğraflar şu an kullanılamıyor.",
        "img_no_chat": "Önce bir karakter seç, sonra fotoğraf isteyebilirsin.",
        "img_failed": "Fotoğraf şu an hazırlanamadı. Kredin iade edildi. Biraz sonra tekrar dene.",
        "img_refused": "{name} bunu gönderemiyor. Kredin iade edildi. Başka bir şey iste.",
        "gallery_empty": "Şu anda gösterilecek karakter yok. Lütfen biraz sonra tekrar bak.",
        "card_open": "💬 {name} ile sohbet et",
        "page_previous": "‹ Önceki",
        "page_next": "Sonraki ›",
        "page_counter": "{page}/{total}",
        "chat_divider": "━━━━━━━━━━━━\n{icon} <b>{name}</b>\n━━━━━━━━━━━━",
        "chat_resumed": "Tekrar hoş geldin! <b>{name}</b> ile sohbetine devam ediyorsun.",
        "chat_new": "<b>{name}</b> ile yeni bir sohbet başladı. Mesajını yazman yeterli.",
        "ask_name": "Sana nasıl hitap edeyim? Bu mesajı yanıtlayarak adını yaz.",
        "name_saved": "Memnun oldum, <b>{name}</b>! Başlamak için bir karakter seç.",
        "name_invalid": "Lütfen sadece bir isim yaz (harf, en fazla 40 karakter). Tekrar denemek için /name.",
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
        "cmd_buy": "Kredi veya abonelik satın al",
        "cmd_terms": "Kullanım şartları",
        "cmd_support": "Destek",
        "cmd_paysupport": "Ödeme yardımı",
        "btn_buy": "💳 Kredi satın al",
        "buy_menu": "Ne almak istersin? Ödeme Telegram Yıldızları ile yapılır. Satın alarak /terms şartlarını kabul edersin.",
        "buy_pack_button": "{credits} kredi — {stars} ⭐",
        "buy_sub_button": "⭐ Abonelik, {days} gün — {stars} ⭐",
        "buy_unavailable": "Şu an satışta bir şey yok.",
        "invoice_pack_title": "{credits} kredi",
        "invoice_pack_description": "Peligrosa sohbet kredisi.",
        "invoice_sub_title": "Abonelik ({days} gün)",
        "invoice_sub_description": "{days} gün boyunca günde {cap} mesaj dahil.",
        "invoice_sub_description_groups": "{days} gün boyunca günde {cap} mesaj ve grup kurma dahil.",
        "precheckout_rejected": "Bu ürün artık satışta değil ya da fiyatı değişti. Lütfen /buy ile tekrar aç.",
        "pay_thanks_pack": "✅ Teşekkürler! Artık <b>{credits}</b> kredin var.",
        "pay_thanks_sub": "✅ Teşekkürler! Aboneliğin <b>{until}</b> tarihine kadar aktif.",
        "pay_problem": "Ödemeni aldık ama otomatik teslim edemedik. Lütfen /paysupport ile bize ulaş ve bu sohbeti silme.",
        "terms_text": (
            "<b>Kullanım şartları</b>\n"
            "• Kredi ve abonelik, Telegram Yıldızları ile ödenen dijital ürünlerdir.\n"
            "• Krediler mesaj yazarak harcanır; cevap alınamazsa kredi otomatik iade edilir.\n"
            "• Karakterler kurgusal yapay zekâ karakterleridir. 18 yaşında veya daha büyük olmalısın.\n"
            "• Sohbetlerin hizmeti geliştirmek ve modellerimizi eğitmek için kullanılabilir. "
            "Bir sohbeti ve karakterin bu sohbetten hatırladıklarını /delete ile silebilirsin. "
            "Verinle ilgili diğer talepler için destekle iletişime geç (/support).\n"
            "• Telegram ve Telegram desteği bu bottaki satın almalarda yardımcı olamaz. /paysupport kullan.\n"
            "• İadeler /paysupport üzerinden tek tek değerlendirilir."
        ),
        "support_text": "Yardım mı lazım? {contact} ile iletişime geç.",
        "paysupport_text": "Ödemeyle ilgili sorun mu var? {contact} ile iletişime geç, ödemenin saatini ve tutarını yaz.",
        "support_missing": "Destek iletişim bilgisi henüz ayarlanmadı.",
        "credits_off": "Kredi sistemi şu an aktif değil.",
        "credits_balance": (
            "💳 <b>{credits}</b> kredin var.\n"
            "Bir mesaj {message}, grup mesajı {group_message}, "
            "grup kurmak {group_create} kredi."
        ),
        "credits_subscribed": (
            "⭐ Aboneliğin <b>{until}</b> tarihine kadar aktif: günde {cap} mesaj dahil. "
            "Ekstra kredi: {credits}."
        ),
        "credits_empty": (
            "Kredin bitti. Sohbete devam etmek için kredi ya da abonelik gerekiyor."
        ),
        "daily_cap": "Bugünkü mesaj sınırına ulaştın. Lütfen yarın tekrar gel.",
        "group_needs_credits": (
            "Grup kurmak {cost} kredi (abonelikte ücretsiz). Senin {credits} kredin var. Daha fazlası için /buy."
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
        "cmd_rename": "Bu sohbeti yeniden adlandır",
        "rename_usage": "Komuttan sonra yeni adı yaz, örn. <code>/rename Film gecesi</code>. Adı kaldırmak için <code>/rename -</code>.",
        "rename_saved": "Sohbet yeniden adlandırıldı: <b>{name}</b>",
        "rename_cleared": "Sohbet adı kaldırıldı.",
        "rename_invalid": "Bu ad kullanılamıyor. Kısa, düz bir ad dene (en fazla 40 karakter).",
        "cmd_name": "Adını değiştir",
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
