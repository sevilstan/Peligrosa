from abc import ABC, abstractmethod


class AIProvider(ABC):

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> str:
        pass
