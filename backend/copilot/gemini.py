"""
Google Generative Language API client — the copilot's only outbound call.

Deliberately small and dependency-light: `requests` and nothing else. It does four
things the rest of the codebase should not have to think about:

  * resolves the API key (runtime override → GEMINI_API_KEY → GOOGLE_API_KEY → .env)
  * picks a model that the supplied key can actually reach, since which models a
    free key is entitled to changes over time — a hardcoded name that 404s is the
    single most likely way this feature breaks on someone else's machine
  * retries the failures that are worth retrying (429, 5xx) and refuses to retry
    the ones that are not (a bad key stays bad)
  * turns both response shapes — one-shot JSON and the SSE stream — into plain text

Failure is never silent and never fabricated: every error path raises a GeminiError
carrying a message intended to be shown to the operator, so the UI can say "your key
was rejected" instead of rendering an empty answer bubble.
"""

import json
import os
import time
from pathlib import Path

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

#: Tried in order the first time a key is used; the first one that answers is
#: remembered for the process. All three are on Google's free tier at the time of
#: writing — the list exists because that entitlement is Google's to change, not
#: ours, and a copilot that dies on a 404 for a retired model name is a bad demo.
MODEL_CANDIDATES = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]

#: Crime typologies, mule accounts and laundering chains are the subject matter
#: here, and the default filters occasionally read that as the user planning one.
#: BLOCK_ONLY_HIGH keeps the genuinely unsafe categories active while letting a
#: forensic analyst discuss the case they are investigating.
SAFETY_SETTINGS = [
    {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
    for c in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 120


class GeminiError(RuntimeError):
    """Any failure talking to Gemini. `status` is the HTTP status to surface."""

    def __init__(self, message, status=502, retryable=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable


class GeminiNotConfigured(GeminiError):
    """No API key available. Distinct because the UI shows a setup panel for it."""

    def __init__(self, message="No Gemini API key configured."):
        super().__init__(message, status=503)


def _load_dotenv_key():
    """
    Read GEMINI_API_KEY out of a .env file without importing python-dotenv.

    Checked in order: repo root, then backend/. Kept as a hand-rolled six-line
    parser so enabling the copilot never turns into a dependency install.
    """
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / ".env", here.parents[1] / ".env"):
        if not candidate.exists():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                    value = value.strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            continue
    return None


class GeminiClient:
    """
    Stateless-per-call client with one piece of remembered state: the model name
    that worked. Instantiated once and held on the app; `set_api_key` lets the
    Settings panel supply a key at runtime for a machine with no .env.
    """

    def __init__(self, api_key=None, model=None):
        self._runtime_key = api_key
        self._preferred_model = model or os.getenv("GEMINI_MODEL") or None
        self._resolved_model = None
        self._session = requests.Session()

    # ── configuration ───────────────────────────────────────────────────────

    @property
    def api_key(self):
        return (
            self._runtime_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or _load_dotenv_key()
        )

    @property
    def configured(self):
        return bool(self.api_key)

    def set_api_key(self, api_key):
        """
        Hold a key for this process only.

        Never written to disk. A key pasted into the Settings panel lives until the
        server restarts — persisting it would mean writing a credential into the
        repo working tree on behalf of a user who only asked to try the feature.
        """
        self._runtime_key = (api_key or "").strip() or None
        self._resolved_model = None
        return self.configured

    def key_fingerprint(self):
        """Last four characters, for confirming *which* key is loaded without leaking it."""
        key = self.api_key
        return f"…{key[-4:]}" if key and len(key) >= 4 else None

    def key_source(self):
        if self._runtime_key:
            return "runtime"
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return "environment"
        if _load_dotenv_key():
            return ".env file"
        return None

    @property
    def model(self):
        return self._resolved_model or self._preferred_model or MODEL_CANDIDATES[0]

    def _model_candidates(self):
        if self._resolved_model:
            return [self._resolved_model]
        ordered = list(MODEL_CANDIDATES)
        if self._preferred_model:
            ordered = [self._preferred_model] + [m for m in ordered if m != self._preferred_model]
        return ordered

    # ── request construction ────────────────────────────────────────────────

    def _payload(self, contents, system_instruction=None, temperature=0.2,
                 max_output_tokens=2048, model=""):
        body = {
            "contents": contents,
            "generationConfig": {
                # Low but not zero: this is an evidence-reporting assistant, and
                # answers should be reproducible enough that two runs on the same
                # question do not read as two different findings.
                "temperature": temperature,
                "topP": 0.9,
                "maxOutputTokens": max_output_tokens,
            },
            "safetySettings": SAFETY_SETTINGS,
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if "2.5" in model:
            # 2.5 models think before answering by default. The reasoning is not
            # shown, it is billed against the free-tier quota, and it adds seconds
            # to a panel the operator is watching — the digest already contains the
            # findings, so there is little for it to reason about.
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        return body

    def _headers(self):
        key = self.api_key
        if not key:
            raise GeminiNotConfigured()
        return {"x-goog-api-key": key, "Content-Type": "application/json"}

    @staticmethod
    def _error_from_response(response):
        """Turn an API error body into a GeminiError with an operator-readable message."""
        status = response.status_code
        detail = ""
        try:
            payload = response.json()
            detail = (payload.get("error") or {}).get("message") or ""
        except (ValueError, AttributeError):
            detail = (response.text or "")[:300]

        lowered = detail.lower()
        if status in (400, 401, 403) and ("api key" in lowered or "api_key" in lowered
                                          or "unauthenticated" in lowered
                                          or "permission" in lowered):
            return GeminiError(
                f"Gemini rejected the API key: {detail or 'invalid credentials'}. "
                "Check the key at https://aistudio.google.com/apikey.",
                status=401,
            )
        if status == 429:
            return GeminiError(
                "Gemini free-tier rate limit reached. Wait a few seconds and ask again."
                + (f" ({detail})" if detail else ""),
                status=429,
                retryable=True,
            )
        if status == 404:
            return GeminiError(
                f"Model not available to this key: {detail or 'not found'}",
                status=404,
            )
        if status >= 500:
            return GeminiError(
                f"Gemini is temporarily unavailable ({status}). {detail}",
                status=503,
                retryable=True,
            )
        return GeminiError(f"Gemini API error {status}: {detail or 'unknown error'}", status=502)

    @staticmethod
    def _extract_text(payload):
        """
        Pull the answer text out of a generateContent response.

        A blocked or truncated generation returns a well-formed response with no
        text in it, which would otherwise surface as an empty chat bubble. Both
        cases raise instead, so the operator is told what happened.
        """
        feedback = payload.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise GeminiError(
                f"Gemini blocked this request ({feedback['blockReason']}). "
                "Rephrase the question.",
                status=422,
            )

        candidates = payload.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no answer for this request.", status=502)

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()

        if not text:
            reason = candidate.get("finishReason") or "unknown"
            if reason == "SAFETY":
                raise GeminiError(
                    "Gemini's safety filter blocked the answer. Rephrase the question.",
                    status=422,
                )
            if reason == "MAX_TOKENS":
                raise GeminiError(
                    "The answer hit the length limit before any text was produced. "
                    "Ask a narrower question.",
                    status=502,
                )
            raise GeminiError(f"Gemini returned an empty answer (finishReason={reason}).", status=502)
        return text

    # ── calls ───────────────────────────────────────────────────────────────

    def generate(self, contents, system_instruction=None, temperature=0.2,
                 max_output_tokens=2048, max_retries=2):
        """One-shot generation. Returns the answer text."""
        last_error = None

        for model in self._model_candidates():
            url = f"{API_ROOT}/models/{model}:generateContent"
            body = self._payload(contents, system_instruction, temperature,
                                 max_output_tokens, model)

            for attempt in range(max_retries + 1):
                try:
                    response = self._session.post(
                        url, headers=self._headers(), json=body,
                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    )
                except requests.Timeout:
                    last_error = GeminiError(
                        "Gemini did not respond in time. Try again.", status=504, retryable=True
                    )
                except requests.RequestException as exc:
                    last_error = GeminiError(
                        f"Could not reach Gemini — check the machine's internet connection. ({exc})",
                        status=503,
                    )
                else:
                    if response.status_code == 200:
                        self._resolved_model = model
                        return self._extract_text(response.json())
                    last_error = self._error_from_response(response)

                if last_error.status == 404:
                    break  # this model is not available — try the next candidate
                if not last_error.retryable or attempt == max_retries:
                    raise last_error
                time.sleep(1.5 * (attempt + 1))

        raise last_error or GeminiError("Gemini request failed.", status=502)

    def stream(self, contents, system_instruction=None, temperature=0.2,
               max_output_tokens=2048):
        """
        Streaming generation. Yields text chunks as they arrive.

        The answer starts appearing in ~1s instead of after the whole 400-word brief
        is written, which is the difference between a panel that looks alive and one
        that looks hung. Model fallback still applies, but only up to the first byte:
        once text has been yielded the caller has already rendered it, so a mid-stream
        failure is raised rather than silently restarted on another model.
        """
        last_error = None

        for model in self._model_candidates():
            url = f"{API_ROOT}/models/{model}:streamGenerateContent"
            body = self._payload(contents, system_instruction, temperature,
                                 max_output_tokens, model)
            emitted = False

            try:
                response = self._session.post(
                    url, headers=self._headers(), json=body, params={"alt": "sse"},
                    stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.Timeout:
                last_error = GeminiError("Gemini did not respond in time. Try again.", status=504)
                continue
            except requests.RequestException as exc:
                raise GeminiError(
                    f"Could not reach Gemini — check the machine's internet connection. ({exc})",
                    status=503,
                )

            if response.status_code != 200:
                last_error = self._error_from_response(response)
                response.close()
                if last_error.status == 404:
                    continue  # try the next model
                raise last_error

            self._resolved_model = model

            # requests falls back to ISO-8859-1 for any text/* response that does
            # not name a charset, which text/event-stream does not. Left alone,
            # iter_lines(decode_unicode=True) decodes UTF-8 bytes as latin-1 and
            # every ₹ in a streamed answer arrives as "â‚¹" — the one-shot path
            # never showed it because .json() gets the encoding right.
            response.encoding = "utf-8"

            try:
                for raw in response.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith("data:"):
                        continue
                    chunk = raw[len("data:") :].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        payload = json.loads(chunk)
                    except ValueError:
                        continue

                    feedback = payload.get("promptFeedback") or {}
                    if feedback.get("blockReason") and not emitted:
                        raise GeminiError(
                            f"Gemini blocked this request ({feedback['blockReason']}). "
                            "Rephrase the question.",
                            status=422,
                        )

                    for candidate in payload.get("candidates") or []:
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            text = part.get("text")
                            if text:
                                emitted = True
                                yield text
                        if candidate.get("finishReason") == "SAFETY" and not emitted:
                            raise GeminiError(
                                "Gemini's safety filter blocked the answer. Rephrase the question.",
                                status=422,
                            )
            finally:
                response.close()

            if not emitted:
                raise GeminiError("Gemini returned an empty answer.", status=502)
            return

        raise last_error or GeminiError("Gemini request failed.", status=502)

    def verify(self):
        """
        Cheap round-trip that proves the key works and pins the model.

        Used by /api/copilot/status and after a key is pasted into Settings, so the
        panel can report "connected" from evidence rather than from the mere presence
        of a non-empty string.
        """
        if not self.configured:
            raise GeminiNotConfigured()
        self.generate(
            [{"role": "user", "parts": [{"text": "Reply with the single word: ready"}]}],
            max_output_tokens=16,
            max_retries=0,
        )
        return self.model
