import json
import os
import time


class ChatBundleBuilder:
    def __init__(self, target_dir, output_dir, context_dir):
        self.target_dir = os.path.abspath(target_dir)
        self.output_dir = os.path.abspath(output_dir)
        self.context_dir = os.path.abspath(context_dir)

    def build(
        self,
        state,
        message="",
        selected_paths=None,
        mode="task",
        max_related_files=12,
        include_context=True,
        include_recent_changes=True,
    ):
        selected_paths = selected_paths or []

        selected_paths = self._normalize_selected_paths(selected_paths, state)
        related_paths = self._resolve_related_paths(
            selected_paths=selected_paths,
            relations=state.get("relations", {}),
            max_related_files=max_related_files,
        )

        bundle_payload = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "message": message,
            "project_state": self._build_project_state_summary(state),
            "selected_files": selected_paths,
            "related_files": related_paths,
            "recent_changes": state.get("recent_changes", [])[:10] if include_recent_changes else [],
            "file_contexts": self._collect_contexts(selected_paths, related_paths) if include_context else {},
            "source_files": self._collect_source_files(selected_paths, related_paths),
        }

        txt_path = os.path.join(self.output_dir, "nexus_chat_bundle.txt")
        json_path = os.path.join(self.output_dir, "nexus_chat_bundle.json")

        with open(txt_path, "w", encoding="utf-8") as file:
            file.write(self._render_text_bundle(bundle_payload))

        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(bundle_payload, file, indent=2)

        return {
            "status": "success",
            "txt_file": "output/nexus_chat_bundle.txt",
            "json_file": "output/nexus_chat_bundle.json",
            "selected_count": len(selected_paths),
            "related_count": len(related_paths),
        }

    def _normalize_selected_paths(self, selected_paths, state):
        known_files = set(state.get("files", {}).keys())
        normalized = []

        for path in selected_paths:
            if path in known_files and path not in normalized:
                normalized.append(path)

        return normalized

    def _resolve_related_paths(self, selected_paths, relations, max_related_files):
        related_candidates = []
        selected_set = set(selected_paths)

        for source_path in selected_paths:
            dependencies = relations.get(source_path, [])
            dependency_names = {dependency for dependency in dependencies if dependency}

            for rel_path in relations.keys():
                if rel_path in selected_set:
                    continue

                filename = os.path.basename(rel_path)
                stem, _ = os.path.splitext(filename)

                if filename in dependency_names or stem in dependency_names:
                    if rel_path not in related_candidates:
                        related_candidates.append(rel_path)

                if len(related_candidates) >= max_related_files:
                    return related_candidates[:max_related_files]

        return related_candidates[:max_related_files]

    def _build_project_state_summary(self, state):
        files = state.get("files", {})
        routes = state.get("routes", [])

        role_counts = {}
        layer_counts = {}

        for info in files.values():
            role = info.get("role", "unknown")
            layer = info.get("layer", "unknown")

            role_counts[role] = role_counts.get(role, 0) + 1
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

        return {
            "file_count": len(files),
            "route_count": len(routes),
            "recent_changes": state.get("recent_changes", [])[:10],
            "layers": layer_counts,
            "roles": role_counts,
            "last_update": state.get("last_update", "Never"),
        }

    def _collect_contexts(self, selected_paths, related_paths):
        contexts = {}
        for rel_path in selected_paths + related_paths:
            context_path = self._get_context_path(rel_path)
            if os.path.exists(context_path):
                try:
                    with open(context_path, "r", encoding="utf-8") as file:
                        contexts[rel_path] = file.read()
                except Exception:
                    pass
        return contexts

    def _collect_source_files(self, selected_paths, related_paths):
        files = {}

        for rel_path in selected_paths + related_paths:
            abs_path = os.path.join(self.target_dir, rel_path)
            if not os.path.exists(abs_path):
                continue

            try:
                with open(abs_path, "r", encoding="utf-8") as file:
                    files[rel_path] = file.read()
            except Exception:
                pass

        return files

    def _get_context_path(self, rel_path):
        safe_name = rel_path.replace("/", "___").replace("\\", "___") + ".md"
        return os.path.join(self.context_dir, safe_name)

    def _render_text_bundle(self, payload):
        lines = []

        lines.append("=== NEXUS CHAT BUNDLE ===")
        lines.append(f"Generated: {payload['generated_at']}")
        lines.append(f"Mode: {payload['mode']}")
        lines.append(f"Message: {payload['message'] or '-'}")
        lines.append("")

        lines.append("=== PROJECT STATE SUMMARY ===")
        lines.append(json.dumps(payload["project_state"], indent=2))
        lines.append("")

        lines.append("=== SELECTED FILES ===")
        if payload["selected_files"]:
            lines.extend([f"- {path}" for path in payload["selected_files"]])
        else:
            lines.append("- None")
        lines.append("")

        lines.append("=== RELATED FILES ===")
        if payload["related_files"]:
            lines.extend([f"- {path}" for path in payload["related_files"]])
        else:
            lines.append("- None")
        lines.append("")

        lines.append("=== RECENT CHANGES ===")
        if payload["recent_changes"]:
            lines.extend([f"- {path}" for path in payload["recent_changes"]])
        else:
            lines.append("- None")
        lines.append("")

        lines.append("=== FILE CONTEXTS ===")
        if payload["file_contexts"]:
            for rel_path, content in payload["file_contexts"].items():
                lines.append(f"--- CONTEXT: {rel_path} ---")
                lines.append(content)
                lines.append("")
        else:
            lines.append("No stored file contexts.")
            lines.append("")

        lines.append("=== SOURCE FILES ===")
        for rel_path, content in payload["source_files"].items():
            lines.append(f"--- FILE: {rel_path} ---")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)
