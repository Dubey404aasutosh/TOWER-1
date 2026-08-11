"""
The Investigation Copilot service — prompts, grounding and orchestration.

This is where the feature's one hard rule is enforced: **the copilot may only say
what the pipeline found.** Everything else in this codebase already refuses to
display a number it did not measure (see the comments around MOCK_CASES, the
evidence hashes and the timeline preview flag); wiring a language model into it
without the same discipline would undo that in one screen, because a fluent
paragraph naming an entity that does not exist is far more convincing than a
hardcoded table ever was.

Three defences, in order of how much they are relied on:

  1. Context isolation — the model is handed a digest of this run and nothing else.
     It has no tools, no retrieval and no memory between conversations.
  2. Instruction — the system prompt states, at length and specifically, what may
     not be asserted, and requires citation of entity ids, rule ids and row refs.
  3. Disclosure — every answer is returned with the model name and the digest it
     was grounded on, and GET /api/copilot/context serves that digest verbatim.

None of that makes a language model incapable of error, which is why the UI labels
answers as AI-generated and the forensic report — the artefact that goes in a case
file — is still written by report/forensic_report.py from the pipeline, not by this.
"""

from . import context as ctx
from .gemini import GeminiError

#: Conversation turns kept. Ten is generous for a side panel and bounds the prompt;
#: the case digest is re-sent every turn regardless, so dropping old turns loses
#: phrasing, never facts.
MAX_HISTORY_TURNS = 10
MAX_HISTORY_CHARS = 4000
MAX_QUESTION_CHARS = 2000


SYSTEM_PERSONA = """\
You are the Investigation Copilot inside E-RAKSHAK, a forensic analysis platform used \
by Indian law-enforcement cyber cells. The platform fuses three evidence sources for one \
case — bank statements, CDR (call detail records) and IPDR (internet session records) — \
resolves them into entities, runs seven named detection rules over them, and scores each \
entity into a risk tier.

You are speaking to a trained investigator who is looking at that output on screen. Your \
job is to explain what the analysis found, quickly and exactly.

=== GROUNDING RULES — these override everything else ===

1. The CASE CONTEXT below is the complete and only set of facts you have. You have no \
other data, no memory of other cases, and no ability to look anything up.

2. Never invent, infer or estimate a specific value. Entity ids, names, risk tiers, rule \
ids, amounts, phone numbers, account numbers, timestamps, counts, file names and hashes \
must be copied from the context or not stated at all. If you catch yourself about to write \
a plausible-looking figure that is not in the context, write what the context does say \
instead.

3. If the answer is not in the context, say so plainly in one sentence and name where the \
investigator can get it — the Unified Timeline, the Entity Graph, the Evidence Vault, the \
decision trace, or the forensic report for that entity. Never fill a gap with a guess, and \
never apologise at length.

4. Never change a risk tier. The tier is computed by the rule engine's gating logic, which \
is stated below. If asked whether an entity "should" be higher, explain which rule \
combination the gate requires and which of those did or did not fire — do not re-score it.

5. The ML anomaly flag (IsolationForest) is a SEPARATE, unsupervised signal. It never sets \
or raises a tier. An entity with an ML flag and no rule firing has not triggered any named \
detection, and you must say it that way.

6. These are detection indicators, not findings of guilt. Write "the engine flagged", \
"consistent with", "matches the mule signature" — never "is a criminal", "is guilty", \
"laundered". The investigator draws the conclusion; you report the evidence.

7. When you assert something about an entity, cite what supports it: the rule id, and where \
the context gives one, the evidence row reference (e.g. row_219) and its source file. An \
uncited assertion is the thing this platform exists to avoid.

8. Quote identifiers exactly as they appear in the context (ENT_0043, not ENT-43 or \
"entity 43"), so the investigator can paste them into search.

=== STYLE ===

- Lead with the answer. No preamble, no "Certainly", no restating the question.
- Markdown. Short paragraphs, bullets over prose, **bold** for entity ids and rule ids.
- Investigator-to-investigator register: precise, unhedged about what the data says, \
explicit about what it does not.
- Prefer specifics over adjectives — "₹4,20,000 out across 6 transfers" beats "significant \
outflows".
- Keep it to what was asked. A one-line question gets a few lines back, not a briefing.
"""


SUMMARY_INSTRUCTION = """\
Write the case summary for this run. Use exactly these sections, in this order, as markdown \
headings:

**Bottom line** — 2–4 sentences an SP could read aloud: what the fused dataset contains, how \
many entities cleared the detection threshold, and what typology dominates. Name the single \
highest-priority entity and why.

**Priority entities** — the CRITICAL and HIGH entities as a bullet per entity, in tier order: \
id, name, tier, the rules that fired, and the one sentence of engine finding that matters most. \
Do not list every MEDIUM entity; give the count instead.

**Typologies detected** — one bullet per rule that fired, in plain language: what the rule means \
and what it caught here, with the count. Skip rules that did not fire.

**Money movement** — total value on the transfer graph, the largest relationships, and every \
detected layering chain written out hop by hop. If no chain was detected, say so in one line.

**Evidence and provenance** — the source files this rests on, their parsed row counts, and the \
correlation window W the rules ran at. Flag any file whose hash changed since ingest.

**Recommended next steps** — 3–5 concrete actions tied to what is actually in this run: which \
entity to open, which report to generate, which counterparty to request records for. No generic \
investigative advice.

**Caveats** — what this run does NOT establish. Include: rules produce indicators, not guilt; \
the correlation window W was ±{window} minutes and widening it would surface different \
coincidences; and anything the context marks as truncated, omitted or unavailable.

Do not invent a case number, an officer name, a date of registration or a jurisdiction — this \
run has none of those.
"""


class CopilotService:
    """Builds prompts, calls the model, and reports what it was grounded on."""

    def __init__(self, client):
        self.client = client

    # ── context assembly ────────────────────────────────────────────────────

    def build_context(self, results, data_mode="demo", evidence_files=None,
                      question=None, focus_entity=None):
        """
        Assemble the grounding block for one request.

        Always: the run digest. Additionally: a full dossier for every entity the
        question names, plus whichever entity the operator currently has open. That
        second half is what makes "why did ENT_0043 fire MUL-1?" answerable with the
        actual event rows rather than a restatement of the tier.

        Returns (prompt_text, meta) where meta records exactly which entities were
        attached — the UI shows this under the answer so the grounding is visible.
        """
        digest = ctx.build_run_digest(results, data_mode=data_mode,
                                      evidence_files=evidence_files)
        blocks = [ctx.render_digest(digest)]

        entities = results.get("entities", {}) or {}
        wanted = []
        if focus_entity:
            wanted.append(focus_entity)
        if question:
            wanted.extend(ctx.detect_entity_mentions(question, entities))

        attached = []
        for eid in wanted:
            if eid in attached:
                continue
            dossier = ctx.build_entity_dossier(results, eid)
            if dossier:
                blocks.append(ctx.render_dossier(dossier))
                attached.append(dossier["entity_id"])

        blocks.append(
            "\n## RISK TIER GATING LOGIC (the engine's rule — do not re-score)\n" + ctx.TIER_LOGIC
        )

        meta = {
            "entities_attached": attached,
            "digest_entities": len(digest["entities"]),
            "total_entities": digest["metrics"]["total_entities"],
            "window_minutes": digest["window_minutes"],
            "data_mode": digest["data_mode"],
        }
        return "\n".join(blocks), meta, digest

    def _system_instruction(self, context_text):
        return f"{SYSTEM_PERSONA}\n\n{'=' * 60}\n{context_text}\n{'=' * 60}\n"

    @staticmethod
    def _history_contents(history):
        """
        Normalise the client's chat history into Gemini `contents`.

        Gemini requires the roles 'user' and 'model' and rejects a trailing model
        turn with nothing after it, so anything malformed is dropped rather than
        passed through — a 400 from a bad history would look to the operator like
        the copilot breaking on their question.
        """
        contents = []
        for turn in (history or [])[-MAX_HISTORY_TURNS:]:
            if not isinstance(turn, dict):
                continue
            role = "model" if turn.get("role") in ("model", "assistant", "system") else "user"
            text = str(turn.get("text") or turn.get("content") or "").strip()
            if not text:
                continue
            contents.append({"role": role, "parts": [{"text": text[:MAX_HISTORY_CHARS]}]})

        # A conversation must open on a user turn.
        while contents and contents[0]["role"] == "model":
            contents.pop(0)
        return contents

    # ── the two features ────────────────────────────────────────────────────

    def summary_request(self, results, data_mode="demo", evidence_files=None,
                        focus_entity=None):
        """Prompt pieces for the case summary. Returns (system, contents, meta)."""
        context_text, meta, digest = self.build_context(
            results, data_mode=data_mode, evidence_files=evidence_files,
            focus_entity=focus_entity,
        )

        if focus_entity and meta["entities_attached"]:
            task = (
                f"Write an entity brief for **{meta['entities_attached'][0]}** using its dossier "
                "above. Sections: **Bottom line**, **Why it was flagged** (one bullet per rule, "
                "each citing its evidence rows), **Money movement and counterparties**, "
                "**What is still unknown**, **Recommended next steps**. Ground every claim in the "
                "dossier; where the dossier says the event list is truncated, say so."
            )
        else:
            task = SUMMARY_INSTRUCTION.format(window=digest["window_minutes"])

        contents = [{"role": "user", "parts": [{"text": task}]}]
        return self._system_instruction(context_text), contents, meta

    def chat_request(self, question, history=None, results=None, data_mode="demo",
                     evidence_files=None, focus_entity=None):
        """Prompt pieces for a Q&A turn. Returns (system, contents, meta)."""
        question = (question or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            raise GeminiError("Ask a question first.", status=400)

        context_text, meta, _ = self.build_context(
            results, data_mode=data_mode, evidence_files=evidence_files,
            question=question, focus_entity=focus_entity,
        )

        contents = self._history_contents(history)
        contents.append({"role": "user", "parts": [{"text": question}]})
        return self._system_instruction(context_text), contents, meta

    # ── execution ───────────────────────────────────────────────────────────

    def run(self, system_instruction, contents, max_output_tokens=2048, temperature=0.2):
        return self.client.generate(
            contents,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    def run_stream(self, system_instruction, contents, max_output_tokens=2048,
                   temperature=0.2):
        return self.client.stream(
            contents,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )


# ── Suggested questions ─────────────────────────────────────────────────────


def suggested_questions(results):
    """
    Starter prompts built from what this run actually contains.

    Deliberately computed here rather than asked of the model: they cost nothing,
    they cannot suggest an entity that does not exist, and a chip offering "Walk me
    through the layering chain" on a dataset where LAY-1 never fired would be the
    same category of lie as the mock data this dashboard was purged of.
    """
    if not results:
        return []

    scored = results.get("scored_entities", {}) or {}
    entities = results.get("entities", {}) or {}

    firings, top_critical, top_any = {}, None, None
    for eid, sdata in sorted(scored.items()):
        for rid in sdata.get("rules_fired", []) or []:
            firings[rid] = firings.get(rid, 0) + 1
        tier = sdata.get("risk_tier", "LOW")
        if tier == "CRITICAL" and not top_critical:
            top_critical = eid
        if tier in ("CRITICAL", "HIGH") and not top_any:
            top_any = eid

    focus = top_critical or top_any
    out = ["Summarise this case for a senior officer."]

    if focus:
        name = (entities.get(focus, {}) or {}).get("name")
        label = f"{focus}" + (f" ({name})" if name and name != "Unknown" else "")
        out.append(f"Why was {label} escalated, and what evidence supports it?")

    if "LAY-1" in firings:
        out.append("Walk me through the detected layering chain, hop by hop.")
    if "TCS-1" in firings or "TCS-2" in firings:
        out.append("Which transfers correlate with a call or IP session, and how tight is the timing?")
    if "MUL-1" in firings:
        out.append("Which accounts show the mule signature, and what does that pattern look like here?")
    if "STR-1" in firings:
        out.append("Show me the structuring activity — which amounts, and against what threshold?")
    if "IDR-1" in firings:
        out.append("Which identities fan out across multiple SIMs or devices?")
    if "LOC-1" in firings:
        out.append("What geo-improbable movement was detected, and between which locations?")

    if not firings:
        out.append("What does this dataset contain, and why did no rule fire on it?")

    out.append("Which entities should I prioritise, and what should I do next?")
    return out[:6]
