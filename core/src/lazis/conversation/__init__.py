"""Conversation engine (Phase 3): persistent chats, context assembly, compaction, streaming.

Conversation history is *not* personal memory: nothing here extracts or stores facts about
the user. Later phases read messages only through explicit, cited interfaces.
"""

from lazis.conversation.engine import ConversationEngine, TurnHandle, TurnRequest

__all__ = ["ConversationEngine", "TurnHandle", "TurnRequest"]
