import requests

from ai_clients.base import BaseAIClient


class GeminiClient(BaseAIClient):
    MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key):
        self.api_key = api_key

    def list_models(self):
        if not self.api_key:
            raise ValueError("Gemini API key missing.")

        response = requests.get(
            self.MODELS_URL,
            params={"key": self.api_key},
            timeout=20,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Gemini models error: {response.status_code} {response.text}")

        models_data = response.json().get("models", [])
        supported = [
            model["name"]
            for model in models_data
            if "generateContent" in model.get("supportedGenerationMethods", [])
        ]

        return supported

    def discover_best_model(self):
        models = self.list_models()
        preferences = [
            "models/gemini-2.5-flash",
            "models/gemini-2.5-pro",
            "models/gemini-1.5-flash",
            "models/gemini-1.5-pro",
            "models/gemini-pro",
        ]

        for preferred in preferences:
            if preferred in models:
                return preferred

        return models[0] if models else None

    def generate(self, prompt, model=None):
        if not self.api_key:
            raise ValueError("Gemini API key missing.")

        active_model = model or self.discover_best_model()
        if not active_model:
            raise ValueError("No Gemini model available.")

        url = f"https://generativelanguage.googleapis.com/v1beta/{active_model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }

        response = requests.post(
            url,
            params={"key": self.api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Gemini API Error: {response.status_code} {response.text}")

        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        return {
            "model": active_model,
            "raw": data,
            "text": text,
        }
