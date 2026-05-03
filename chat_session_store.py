class ChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages
        self.sessions = {}

    def get_history(self, session_id):
        return self.sessions.get(session_id, [])

    def append_exchange(self, session_id, user_message, assistant_message):
        history = self.sessions.get(session_id, [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        self.sessions[session_id] = history[-self.max_messages:]

    def clear(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
