from ai_clients.gemini_client import GeminiClient
from ai_clients.openai_client import OpenAIClient


class AIClientFactory:
    @staticmethod
    def build(provider, settings):
        provider_name = (provider or "gemini").strip().lower()

        if provider_name == "openai":
            return OpenAIClient(settings.get("openai_api_key"))

        return GeminiClient(settings.get("gemini_api_key"))
