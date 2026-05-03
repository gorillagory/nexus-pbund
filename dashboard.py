from flask import Flask, jsonify, render_template, request


class NexusDashboard:
    def __init__(self, engine):
        self.app = Flask(__name__)
        self.engine = engine

        @self.app.route("/")
        def index():
            return render_template("index.html")

        @self.app.route("/api/state")
        def get_state():
            return jsonify(self.engine.state)

        @self.app.route("/api/settings", methods=["GET"])
        def get_settings():
            return jsonify(self.engine.settings)

        @self.app.route("/api/settings", methods=["POST"])
        def save_settings():
            data = request.json or {}
            result = self.engine.save_settings(data)
            return jsonify(result)

        @self.app.route("/api/models", methods=["GET"])
        def list_models():
            provider = request.args.get("provider")
            force = request.args.get("force", "false").lower() == "true"
            result = self.engine.list_models(provider=provider, force=force)
            return jsonify(result)

        @self.app.route("/api/models/curated", methods=["GET"])
        def list_curated_models():
            provider = request.args.get("provider")
            result = self.engine.list_curated_models(provider=provider)
            return jsonify(result)

        @self.app.route("/api/bundle-self", methods=["POST"])
        def bundle_nexus():
            out_file = self.engine.bundle_self()
            return jsonify({"status": "success", "file": out_file})

        @self.app.route("/api/bundle", methods=["POST"])
        def bundle_selected():
            payload = request.json or {}
            paths = payload.get("paths", [])

            if not paths:
                return jsonify({"status": "error", "message": "No selection"}), 400

            out_file = self.engine.bundle_focused(paths)
            return jsonify({"status": "success", "file": out_file})

        @self.app.route("/api/chat-bundle", methods=["POST"])
        def build_chat_bundle():
            payload = request.json or {}
            message = (payload.get("message") or "").strip()
            selected_paths = payload.get("selected_paths", [])
            mode = (payload.get("mode") or "task").strip()

            result = self.engine.build_chat_bundle(
                message=message,
                selected_paths=selected_paths,
                mode=mode,
            )
            return jsonify(result)

        @self.app.route("/api/context", methods=["GET"])
        def get_context():
            path = request.args.get("path")
            content = self.engine.read_context(path)

            if content:
                return jsonify({"status": "success", "data": content})

            return jsonify({"status": "empty", "data": None})

        @self.app.route("/api/context", methods=["POST"])
        def build_context():
            payload = request.json or {}
            path = payload.get("path")
            result = self.engine.build_ai_context(path)
            return jsonify(result)

        @self.app.route("/api/generate-gem-context", methods=["POST"])
        def generate_gem_context():
            result = self.engine.generate_gem_context()
            return jsonify(result)

        @self.app.route("/api/ai-tool", methods=["POST"])
        def run_ai_tool():
            payload = request.json or {}
            tool_type = payload.get("type")
            result = self.engine.run_ai_tool(tool_type)
            return jsonify(result)

        @self.app.route("/api/chat", methods=["POST"])
        def chat():
            payload = request.json or {}

            session_id = payload.get("session_id", "default")
            message = (payload.get("message") or "").strip()
            selected_paths = payload.get("selected_paths", [])
            mode = payload.get("mode", "ask")

            if not message:
                return jsonify({"status": "error", "message": "Message is required."}), 400

            result = self.engine.chat(
                session_id=session_id,
                message=message,
                selected_paths=selected_paths,
                mode=mode,
            )
            return jsonify(result)

    def run(self, port=5000):
        self.app.run(port=port, debug=False, use_reloader=False)
