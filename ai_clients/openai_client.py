import requests

from ai_clients.base import BaseAIClient


class OpenAIClient(BaseAIClient):
    MODELS_URL = "https://api.openai.com/v1/models"
    RESPONSES_URL = "https://api.openai.com/v1/responses"

    def __init__(self, api_key):
        self.api_key = api_key

    def list_models(self):
        if not self.api_key:
            raise ValueError("OpenAI API key missing.")

        response = requests.get(
            self.MODELS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=20,
        )

        if response.status_code != 200:
            raise RuntimeError(f"OpenAI models error: {response.status_code} {response.text}")

        models = response.json().get("data", [])
        ids = [model["id"] for model in models if model.get("id")]

        preferred = [
            model_id
            for model_id in ids
            if model_id.startswith("gpt") or "o" in model_id.lower()
        ]

        return preferred or ids

    def discover_best_model(self):
        models = self.list_models()
        preferences = [
            "gpt-5.5",
            "gpt-5",
        ]

        for preferred in preferences:
            if preferred in models:
                return preferred

        return models[0] if models else None

    def generate(self, prompt, model=None):
        if not self.api_key:
            raise ValueError("OpenAI API key missing.")

        active_model = model or self.discover_best_model()
        if not active_model:
            raise ValueError("No OpenAI model available.")

        response = requests.post(
            self.RESPONSES_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": active_model,
                "input": prompt,
            },
            timeout=120,
        )

        if response.status_code != 200:
            raise RuntimeError(f"OpenAI API Error: {response.status_code} {response.text}")

        data = response.json()
        text = self._extract_text(data)

        return {
            "model": active_model,
            "raw": data,
            "text": text,
        }

    def _extract_text(self, data):
        output = data.get("output", [])

        for item in output:
            if item.get("type") != "message":
                continue

            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content.get("text", "")

        raise RuntimeError("OpenAI response did not contain output_text.")
