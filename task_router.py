class TaskRouter:
    AGENT_MODEL_ROUTING = {
        "qa_agent": {
            "task_profile": "fast",
            "provider_order": ("gemini", "openai"),
        },
        "cartographer": {
            "task_profile": "fast",
            "provider_order": ("gemini", "openai"),
        },
        "cto": {
            "task_profile": "deep",
            "provider_order": ("openai", "gemini"),
        },
        "architect": {
            "task_profile": "deep",
            "provider_order": ("openai", "gemini"),
        },
        "tech_lead": {
            "task_profile": "deep",
            "provider_order": ("openai", "gemini"),
        },
    }

    MODE_TO_PROFILE = {
        "ask": "balanced",
        "analyze": "analysis",
        "plan": "deep",
        "cto": "deep",
        "architect": "deep",
        "tech_lead": "deep",
        "refactor": "refactor",
        "context": "analysis",
        "audit": "analysis",
        "erd": "fast",
        "bundle": "fast",
    }

    TOOL_TO_PROFILE = {
        "audit": "analysis",
        "erd": "fast",
        "gem_context": "deep",
        "context": "analysis",
        "chat": "balanced",
        "bundle": "fast",
    }

    @classmethod
    def resolve_agent_route(cls, agent_role):
        normalized_role = (agent_role or "").strip().lower()
        return cls.AGENT_MODEL_ROUTING.get(normalized_role)

    @classmethod
    def resolve_profile(cls, mode=None, tool_type=None, explicit_profile=None, agent_role=None):
        if explicit_profile:
            return explicit_profile.strip().lower()

        agent_route = cls.resolve_agent_route(agent_role or mode)
        if agent_route:
            return agent_route["task_profile"]

        if tool_type:
            resolved = cls.TOOL_TO_PROFILE.get(tool_type.strip().lower())
            if resolved:
                return resolved

        if mode:
            resolved = cls.MODE_TO_PROFILE.get(mode.strip().lower())
            if resolved:
                return resolved

        return "balanced"
