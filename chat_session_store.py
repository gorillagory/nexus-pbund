from sqlalchemy import delete, select

from database import get_db, init_db
from models import ChatSession, Message
# Triggering the Cartographer

class ChatSessionStore:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages
        init_db()

    def get_history(self, session_id):
        db_context = get_db()
        db = next(db_context)
        try:
            messages = db.execute(
                select(Message)
                .where(Message.session_id == str(session_id))
                .order_by(Message.created_at.asc(), Message.id.asc())
            ).scalars().all()
            return [
                {"role": message.role, "content": message.content}
                for message in messages[-self.max_messages:]
            ]
        finally:
            db_context.close()

    def append_exchange(self, session_id, user_message, assistant_message):
        session_id = str(session_id)
        db_context = get_db()
        db = next(db_context)
        try:
            chat_session = db.get(ChatSession, session_id)
            if chat_session is None:
                db.add(ChatSession(id=session_id, active_persona="default"))

            db.add_all(
                [
                    Message(
                        session_id=session_id,
                        role="user",
                        content=user_message,
                    ),
                    Message(
                        session_id=session_id,
                        role="assistant",
                        content=assistant_message,
                    ),
                ]
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db_context.close()

    def clear(self, session_id):
        db_context = get_db()
        db = next(db_context)
        try:
            db.execute(delete(Message).where(Message.session_id == str(session_id)))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db_context.close()
