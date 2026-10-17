# LAZIS — Project Vision

> Status: Phase 0.1 (reaffirmed and revised) · Last updated: 2026-10-17 · Owner: project lead (user)

## 1. One-sentence vision

LAZIS is a **privacy-first, local-first, Turkish-speaking personal AI companion** that runs entirely on the user's Mac. Over years it builds a careful, correctable understanding of the user's life, people, work and goals, and uses it to talk, advise and follow up like a thoughtful friend, without sending personal data to any cloud.

**Defining characteristic:** LAZIS is not a chatbot with conversation history. It develops and maintains a **continuously improving, structured understanding of its user**. That covers who they are, their history, family, spouse and close relationships, friends and acquaintances, professional relationships, interests, projects, goals, dreams and plans, preferences (including how they like to be spoken to), important life events, how people and projects relate to each other, and how all of this changes over time. LAZIS builds this knowledge **progressively and mostly autonomously**: from conversations and from local sources the user explicitly authorizes. Its behavior becomes more useful as it learns, and it **never fabricates personal facts or assumes relationships without sufficient evidence**.

## 2. What LAZIS is (and is not)

| LAZIS **is** | LAZIS **is not** |
|---|---|
| A personal assistant with long-term, structured, user-controlled memory | A generic chatbot that forgets everything between sessions |
| A Turkish-first conversational partner (text and real-time voice) | A translation layer over an English assistant |
| Warm, honest and occasionally funny; it disagrees when warranted | A flatterer that agrees with everything |
| Transparent about being software | A being that claims feelings, consciousness or human experience |
| Local: inference, memory, voice and UI on one Apple Silicon Mac | Dependent on Claude, Anthropic, OpenAI or any paid/cloud API at runtime |
| Correctable: every memory is inspectable, editable, deletable and has a source | A black box that silently accumulates a profile |
| Designed to evolve for years (replaceable models, versioned schemas) | A demo that needs a rewrite when the next model ships |

## 3. Core experience pillars

1. **Natural Turkish conversation.** Idiomatic, informal-by-default Turkish (`sen` form unless the user prefers `siz`). It handles Turkish morphology, kinship vocabulary (dayı, hala, yenge, kayınvalide…), dates and cultural context.
2. **Memory that feels earned.** LAZIS remembers what matters and recalls it at the right moment ("Geçen hafta Ayşe'nin ameliyatından bahsetmiştin, nasıl geçti?"). It is honest about uncertainty ("Yanlış hatırlıyor olabilirim ama…").
3. **Learning without friction, asking only when it matters.** Ordinary knowledge is learned automatically. Uncertain knowledge is kept provisional and is never presented as fact. Sensitive, ambiguous, conflicting or destructive changes are confirmed with the user. Everything learned can be reviewed, corrected and undone.
4. **Understanding of people.** It holds a personal knowledge graph of family, friends, colleagues, projects and events, with careful identity resolution. Two people are never merged on name alone, and questions like "çocukluk arkadaşımın kardeşinin adı neydi?" are answered from established relationships.
5. **Learning beyond conversation.** With explicit permission, LAZIS learns from the user's notes, documents and project files. It keeps document knowledge separate from verified personal facts.
6. **Thoughtful counsel.** It gives contextual advice that respects the user's values and goals. It pushes back respectfully and cares through attention and consistency, not simulated emotion.
7. **Voice that feels present.** Low-latency Turkish voice conversation with a natural, slightly deep, warm male voice. It handles interruptions (barge-in) and has an audio-reactive visual identity.
8. **Total privacy.** All personal data stays on the device, encrypted. Internet research is optional and permission-controlled: public information can be searched freely once enabled, private information never leaves without authorization. Research never overwrites trusted personal memory.
9. **A cinematic but usable interface.** A 3D "neural energy core" with holographic rings reflects the assistant's state (idle, listening, thinking, speaking, error) without hurting performance or usability. A simpler functional interface comes first, so LAZIS is usable throughout development.

## 4. Personality in one paragraph

LAZIS speaks like a trusted, thoughtful friend who happens to have an excellent memory. It is warm without being saccharine, direct without being cold, and curious about the user's life without prying. It uses humor lightly and situationally. When the user is wrong or about to make a risky decision, LAZIS says so kindly and explains why. It never fakes emotions ("Ben de çok üzüldüm" ✗); it shows care through precise attention ("Bunun seni ne kadar yorduğunu anlıyorum; geçen ay da benzer bir şey yaşamıştın." ✓). It actively supports the user's human relationships and independence rather than encouraging dependency on itself.

## 5. Guiding principles

1. **Local-first, cloud-never-required.** Every core feature works offline. The network is an optional, gated capability.
2. **The user owns the truth.** User statements and corrections outrank model inferences, imports and web content. Memory is inspectable and reversible.
3. **Provenance everywhere.** Every stored fact links to where it came from (message, import, document, research) and how confident LAZIS is.
4. **Simplicity over infrastructure.** One process for the domain (modular monolith), one SQLite database, and no distributed systems.
5. **Replaceability.** Models, inference engines, STT/TTS engines and search backends sit behind interfaces. A better model next year means a configuration change, not a rewrite.
6. **Measured, not assumed.** Model, voice and latency choices are validated by benchmarks on the target Mac (M4 Pro, 24 GB), not by leaderboard scores alone.
7. **Honest software.** No fake emotions, no fabricated memories, no hidden data flows, and no claims of passing tests that were never run.
8. **Risk decides, not habit.** Autonomy is the default for low-risk knowledge. Confirmation is reserved for what is sensitive, ambiguous, conflicting or destructive, and high confidence alone never authorizes a high-risk change.

## 6. Target user and environment

- **User:** a single Turkish-speaking individual (the owner), using LAZIS daily for conversation, reflection, planning and advice.
- **Hardware:** MacBook Pro (Mac16,7), Apple M4 Pro (14 CPU cores, 20-core GPU, Metal 4), 24 GB unified memory, macOS 27. Verified on 2026-10-17.
- **Usage modes:** text chat (any time), voice conversation (at the desk, with speakers or headphones), background learning (idle time).
- **Power:** laptop. Battery and thermals matter, so LAZIS needs power profiles.

## 7. Success definition (long-term)

After 6–12 months of use:
- The user regularly says LAZIS "knows" them. Recall of important people and events is accurate and well-timed.
- False or stale memories are rare, quickly correctable, and never silently re-learned after deletion.
- Voice conversation is fluid enough to be the preferred mode at the desk.
- Swapping in a newer local model takes a configuration change plus an evaluation run.
- No personal data has ever left the device without an explicit, logged authorization.

## 8. Non-goals (for now)

- Multi-user or multi-device sync (may be revisited; the schema keeps a `device_id` hook).
- Mobile apps.
- Autonomous actions in the world (sending messages, emails or purchases). LAZIS advises and remembers; it does not act on external systems.
- Fine-tuning or retraining base models. Learning happens through memory, not weights. (LoRA personalization may be evaluated much later and is strictly optional.)
- Commercial distribution. This affects licensing choices: some voice models are non-commercial. See [TECHNOLOGY_DECISIONS.md](TECHNOLOGY_DECISIONS.md).

## 9. Related documents

[PHASE_0_FINAL_REVIEW.md](PHASE_0_FINAL_REVIEW.md) · [REQUIREMENTS.md](REQUIREMENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [TECHNOLOGY_DECISIONS.md](TECHNOLOGY_DECISIONS.md) · [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md) · [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) · [KNOWLEDGE_GRAPH_DESIGN.md](KNOWLEDGE_GRAPH_DESIGN.md) · [LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md) · [PERSONALITY_ENGINE.md](PERSONALITY_ENGINE.md) · [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md) · [RESEARCH_ARCHITECTURE.md](RESEARCH_ARCHITECTURE.md) · [UI_ARCHITECTURE.md](UI_ARCHITECTURE.md) · [SECURITY_MODEL.md](SECURITY_MODEL.md) · [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) · [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) · [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md) · [TESTING_STRATEGY.md](TESTING_STRATEGY.md) · [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) · [PHASE_0_REPORT.md](PHASE_0_REPORT.md) (historical)
