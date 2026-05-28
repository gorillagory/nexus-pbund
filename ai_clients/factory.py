import os

from dotenv import load_dotenv

from ai_clients.gemini_client import GeminiClient
from ai_clients.openai_client import OpenAIClient


load_dotenv()


class AIClientFactory:
    @staticmethod
    def build(provider, settings):
        provider_name = (provider or "gemini").strip().lower()

        if provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key is None:
                api_key = settings.get("openai_api_key")
            return OpenAIClient(api_key)

        api_key = os.getenv("GEMINI_API_KEY")
        if api_key is None:
            api_key = settings.get("gemini_api_key")
        return GeminiClient(api_key)
