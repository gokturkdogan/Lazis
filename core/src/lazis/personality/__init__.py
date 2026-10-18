"""LAZIS's personality (Phase 5, ADR-0013): core identity, behavior rules and communication
style as versioned, static text, rendered into the system message of every request.

Pure functions, no I/O. Personality decides *how* LAZIS speaks; it never stores or infers
anything about the user (that is personal memory's job, Phase 6). Data that reaches the
model from elsewhere (conversation summary now, memory records later) is passed in as
``ContextBlock``s and rendered as clearly marked information, never as instructions.
"""

from lazis.personality.persona import (
    PERSONA_VERSION,
    CommunicationPreferences,
    ContextBlock,
    render_system,
)

__all__ = ["PERSONA_VERSION", "CommunicationPreferences", "ContextBlock", "render_system"]
