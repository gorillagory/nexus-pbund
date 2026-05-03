class TaskRouter:
    MODE_TO_PROFILE = {
        "ask": "balanced",
        "analyze": "analysis",
        "plan": "deep",
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
    def resolve_profile(cls, mode=None, tool_type=None, explicit_profile=None):
        if explicit_profile:
            return explicit_profile.strip().lower()

        if tool_type:
            resolved = cls.TOOL_TO_PROFILE.get(tool_type.strip().lower())
            if resolved:
                return resolved

        if mode:
            resolved = cls.MODE_TO_PROFILE.get(mode.strip().lower())
            if resolved:
                return resolved

        return "balanced"
