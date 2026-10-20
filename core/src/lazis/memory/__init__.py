"""Personal memory (Phase 6, ADR-0014): what LAZIS knows about the user, the people and the
projects in their life — with evidence, history, sensitivity rules and real forgetting.

Layers inside the package (no module talks to the model directly; the conversation engine
owns the runtime and passes model output in):

* ``text``, ``registry`` — Turkish matching helpers, predicate semantics;
* ``repository`` — SQL (0004_memory) and the FTS index;
* ``extraction`` — prompt/schema for turning a user message into candidates, and validation;
* ``policy`` — sensitivity, durability, instruction-like content;
* ``resolver`` — which person/project a candidate is about (never guesses between two);
* ``consolidation`` — duplicate, update or conflict against what is stored;
* ``service`` — the orchestrator: apply, forget, edit, merge/split, inbox;
* ``retrieval`` — the per-turn memory context;
* ``commands`` — explicit "hatırla / unut / ne biliyorsun" handling;
* ``importer`` — the starting profile (preview, then apply).
"""
