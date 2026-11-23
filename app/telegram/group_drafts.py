class GroupDrafts:
    """Characters a user has ticked while building a group.

    Kept in memory on purpose: it is a few seconds of UI state, not data.
    After a restart a half-built selection simply "expires" and the user
    starts again; nothing is saved until the group is created.
    """

    def __init__(self):
        self._drafts: dict[int, list[str]] = {}

    def start(self, user_id: int) -> None:
        self._drafts[user_id] = []

    def get(self, user_id: int) -> list[str] | None:
        draft = self._drafts.get(user_id)
        return list(draft) if draft is not None else None

    def toggle(self, user_id: int, slug: str, limit: int) -> bool:
        """Tick or untick a character. False when the group is already full."""
        draft = self._drafts[user_id]
        if slug in draft:
            draft.remove(slug)
        elif len(draft) >= limit:
            return False
        else:
            draft.append(slug)
        return True

    def clear(self, user_id: int) -> None:
        self._drafts.pop(user_id, None)
