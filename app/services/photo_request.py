"""Does a chat message ask the character for a picture? (no AI call)

A cheap word check in Turkish and English. It only decides whether to OFFER a
picture; the user still has to say yes, so a wrong guess costs one extra
message, never credits.
"""

import re

_NOUN = re.compile(
    r"\b(foto\w*|fotoğraf\w*|resim\w*|görsel\w*|selfie\w*|pic|pics|photo\w*|picture\w*|image\w*)",
    re.IGNORECASE,
)
_ASK = re.compile(
    r"\b(at|atsana|atar|atarmısın|atar\s+mısın|yolla\w*|gönder\w*|çek\w*|göster\w*|paylaş\w*|"
    r"send|show|take|share|snap|see)\b",
    re.IGNORECASE,
)
# "can I see you", "seni görebilir miyim", "kendini göster"
_SEE_YOU = re.compile(
    r"(can i see you|let me see you|seni görmek|seni görebilir|kendini göster|nasıl görünüyorsun|what do you look like)",
    re.IGNORECASE,
)
# "I took a photo yesterday" is a story, not a request.
_PAST = re.compile(r"\b(took|taken|çektim|çektik|gönderdim|attım|yolladım|sent)\b", re.IGNORECASE)


def wants_photo(text: str | None) -> bool:
    text = (text or "").strip()
    if not text or len(text) > 300:
        return False
    if _SEE_YOU.search(text):
        return True
    if _NOUN.search(text) and _ASK.search(text) and not _PAST.search(text):
        return True
    return False
