"""
Investigation Copilot — the LLM layer over a completed pipeline run.

Three pieces, deliberately separated:

  context.py  — turns the in-memory run into a compact, *factual* digest. Nothing
                in here is generated; every number is read off the pipeline.
  gemini.py   — the transport. Google Generative Language API, nothing else.
  service.py  — the prompts. This is where grounding is enforced: the model is
                given the digest and told, in the system instruction, that it may
                not assert anything the digest does not contain.

The split matters because the digest is the audit surface. If the copilot ever
states a figure an investigator disputes, the question "where did that come
from?" is answered by dumping the digest for that run — which is exactly what
GET /api/copilot/context does.
"""

from .gemini import GeminiClient, GeminiError, GeminiNotConfigured  # noqa: F401
from .service import CopilotService  # noqa: F401

__all__ = ["GeminiClient", "GeminiError", "GeminiNotConfigured", "CopilotService"]
