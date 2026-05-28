import time

from ai_clients.factory import AIClientFactory


class ModelRegistry:
    CACHE_TTL_SECONDS = 900

    GEMINI_ALLOWED_PATTERNS = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ]

    OPENAI_ALLOWED_PATTERNS = [
        "gpt-5.5",
        "gpt-5",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "o4",
        "o3",
        "o1",
    ]

    def __init__(self, settings):
        self.settings = settings
        self._cache = {
            "gemini": {"fetched_at": 0, "models": []},
            "openai": {"fetched_at": 0, "models": []},
        }

    def refresh(self, provider=None, force=False):
        if provider:
            return self._refresh_provider(provider, force=force)

        return {
            "gemini": self._refresh_provider("gemini", force=force),
            "openai": self._refresh_provider("openai", force=force),
        }

    def list_models(self, provider):
        provider = (provider or "").strip().lower()
        cache_entry = self._cache.get(provider)

        if not cache_entry:
            return []

        now = time.time()
        if now - cache_entry["fetched_at"] > self.CACHE_TTL_SECONDS:
            result = self._refresh_provider(provider, force=True)
            if result.get("status") == "success":
                return result.get("models", [])
            return []

        return cache_entry.get("models", [])

    def list_curated_models(self, provider):
        raw_models = self.list_models(provider)
        return self._curate_models(provider, raw_models)

    def get_curated_catalog(self, provider=None):
        if provider:
            provider = provider.strip().lower()
            raw_models = self.list_models(provider)
            curated_models = self._curate_models(provider, raw_models)
            recommended = self._build_recommendations(provider, curated_models)

            return {
                "status": "success",
                "provider": provider,
                "recommended": recommended,
                "curated_models": curated_models,
                "raw_count": len(raw_models),
                "curated_count": len(curated_models),
            }

        gemini = self.get_curated_catalog("gemini")
        openai = self.get_curated_catalog("openai")

        return {
            "status": "success",
            "gemini": gemini,
            "openai": openai,
        }

    def choose(
        self,
        task_profile="auto",
        provider_preference="auto",
        manual_overrides=None,
        use_configured_fallback=True,
    ):
        manual_overrides = manual_overrides or {}
        task_profile = (task_profile or "auto").strip().lower()
        provider_preference = (provider_preference or "auto").strip().lower()

        if provider_preference in {"gemini", "openai"}:
            resolved = self._choose_for_provider(
                provider=provider_preference,
                task_profile=task_profile,
                manual_model=manual_overrides.get(provider_preference),
                use_configured_fallback=use_configured_fallback,
            )
            if resolved:
                return resolved

        provider_order = self._get_provider_order(task_profile)

        for provider in provider_order:
            resolved = self._choose_for_provider(
                provider=provider,
                task_profile=task_profile,
                manual_model=manual_overrides.get(provider),
                use_configured_fallback=use_configured_fallback,
            )
            if resolved:
                return resolved

        return {
            "provider": "gemini",
            "model": manual_overrides.get("gemini") or self._fallback_model(
                "gemini",
                task_profile,
                use_configured_model=use_configured_fallback,
            ),
            "task_profile": task_profile,
            "selection_mode": "fallback",
        }

    def _choose_for_provider(
        self,
        provider,
        task_profile,
        manual_model=None,
        use_configured_fallback=True,
    ):
        if manual_model:
            return {
                "provider": provider,
                "model": manual_model,
                "task_profile": task_profile,
                "selection_mode": "manual",
            }

        curated_models = self.list_curated_models(provider)
        if not curated_models:
            refreshed = self._refresh_provider(provider, force=True)
            if refreshed.get("status") == "success":
                curated_models = self._curate_models(provider, refreshed.get("models", []))

        chosen = self._pick_best_model(provider, task_profile, curated_models)
        if not chosen:
            chosen = self._fallback_model(
                provider,
                task_profile,
                use_configured_model=use_configured_fallback,
            )

        if not chosen:
            return None

        return {
            "provider": provider,
            "model": chosen,
            "task_profile": task_profile,
            "selection_mode": "auto",
        }

    def _get_provider_order(self, task_profile):
        if task_profile in {"bulk", "fast"}:
            return ["gemini", "openai"]

        if task_profile in {"deep", "coding", "analysis", "refactor"}:
            return ["openai", "gemini"]

        return ["openai", "gemini"]

    def _pick_best_model(self, provider, task_profile, models):
        normalized = [model for model in models if model]

        if provider == "gemini":
            return self._pick_gemini_model(task_profile, normalized)

        if provider == "openai":
            return self._pick_openai_model(task_profile, normalized)

        return None

    def _pick_gemini_model(self, task_profile, models):
        ranked_patterns = {
            "fast": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
            "bulk": ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"],
            "balanced": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
            "auto": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
            "plan": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"],
            "analysis": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"],
            "deep": ["gemini-2.5-pro", "gemini-1.5-pro"],
            "coding": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"],
            "refactor": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"],
        }

        patterns = ranked_patterns.get(task_profile, ranked_patterns["auto"])
        return self._match_by_patterns(
            models,
            patterns,
            allow_unmatched=task_profile not in {
                "fast",
                "bulk",
                "plan",
                "analysis",
                "deep",
                "coding",
                "refactor",
            },
        )

    def _pick_openai_model(self, task_profile, models):
        if task_profile in {"plan", "analysis", "deep", "coding", "refactor"}:
            models = [
                model
                for model in models
                if "mini" not in model.lower() and "nano" not in model.lower()
            ]

        ranked_patterns = {
            "fast": ["gpt-5.4-mini", "o4-mini", "o3-mini"],
            "bulk": ["gpt-5.4-nano", "gpt-5.4-mini", "o4-mini", "o3-mini"],
            "balanced": ["gpt-5", "gpt-5.4-mini", "o4-mini"],
            "auto": ["gpt-5.5", "gpt-5", "gpt-5.4-mini", "o4"],
            "plan": ["gpt-5.5", "gpt-5", "o4"],
            "analysis": ["gpt-5.5", "gpt-5", "o4"],
            "deep": ["gpt-5.5", "gpt-5", "o4"],
            "coding": ["gpt-5.5", "gpt-5", "o4"],
            "refactor": ["gpt-5.5", "gpt-5", "o4"],
        }

        patterns = ranked_patterns.get(task_profile, ranked_patterns["auto"])
        return self._match_by_patterns(
            models,
            patterns,
            allow_unmatched=task_profile not in {
                "fast",
                "bulk",
                "plan",
                "analysis",
                "deep",
                "coding",
                "refactor",
            },
        )

    def _match_by_patterns(self, models, patterns, allow_unmatched=True):
        lower_map = {model.lower(): model for model in models}

        for pattern in patterns:
            for lowered, original in lower_map.items():
                if pattern in lowered:
                    return original

        return models[0] if models and allow_unmatched else None

    def _fallback_model(self, provider, task_profile, use_configured_model=True):
        settings_key = f"{provider}_model"
        configured = (self.settings.get(settings_key) or "").strip()
        if configured and use_configured_model:
            return configured

        if provider == "gemini":
            if task_profile in {"fast", "bulk"}:
                return "models/gemini-2.5-flash"
            return "models/gemini-2.5-pro"

        if provider == "openai":
            if task_profile in {"fast", "bulk"}:
                return "gpt-5.4-mini"
            return "gpt-5.5"

        return None

    def _refresh_provider(self, provider, force=False):
        provider = (provider or "").strip().lower()
        cache_entry = self._cache.get(provider)
        if not cache_entry:
            return {"status": "error", "message": f"Unsupported provider: {provider}"}

        now = time.time()
        if not force and now - cache_entry["fetched_at"] <= self.CACHE_TTL_SECONDS:
            curated_models = self._curate_models(provider, cache_entry["models"])
            return {
                "status": "success",
                "provider": provider,
                "models": cache_entry["models"],
                "curated_models": curated_models,
                "cached": True,
            }

        try:
            client = AIClientFactory.build(provider, self.settings)
            models = client.list_models()
            cache_entry["models"] = models
            cache_entry["fetched_at"] = now
            curated_models = self._curate_models(provider, models)

            return {
                "status": "success",
                "provider": provider,
                "models": models,
                "curated_models": curated_models,
                "cached": False,
            }
        except Exception as exception:
            return {
                "status": "error",
                "provider": provider,
                "message": str(exception),
            }

    def _curate_models(self, provider, models):
        provider = (provider or "").strip().lower()
        models = list(dict.fromkeys(models))

        if provider == "gemini":
            curated = self._filter_models_by_patterns(models, self.GEMINI_ALLOWED_PATTERNS)
            return curated or models[:10]

        if provider == "openai":
            curated = self._filter_models_by_patterns(models, self.OPENAI_ALLOWED_PATTERNS)
            curated = [model for model in curated if not self._is_openai_legacy_model(model)]
            return curated or []

        return models

    def _filter_models_by_patterns(self, models, patterns):
        curated = []
        lowered_patterns = [pattern.lower() for pattern in patterns]

        for pattern in lowered_patterns:
            for model in models:
                if pattern in model.lower() and model not in curated:
                    curated.append(model)

        return curated

    def _is_openai_legacy_model(self, model):
        lowered = model.lower()

        legacy_patterns = [
            "gpt-3.5",
            "gpt-4-0314",
            "gpt-4-0613",
            "gpt-4-1106",
            "gpt-4-0125",
            "instruct",
            "vision-preview",
            "turbo-preview",
            "davinci",
            "babbage",
            "curie",
        ]

        for pattern in legacy_patterns:
            if pattern in lowered:
                return True

        return False

    def _build_recommendations(self, provider, models):
        return {
            "fast": self._pick_best_model(provider, "fast", models),
            "balanced": self._pick_best_model(provider, "balanced", models),
            "deep": self._pick_best_model(provider, "deep", models),
            "coding": self._pick_best_model(provider, "coding", models),
            "bulk": self._pick_best_model(provider, "bulk", models),
        }
