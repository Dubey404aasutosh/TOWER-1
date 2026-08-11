"""
Supabase Storage client — durable home for reports, STRs and evidence files.

Deliberately small and dependency-light, in the same spirit as
`backend/copilot/gemini.py`: `requests` and nothing else. Adding `supabase-py`
would pull in gotrue, postgrest, realtime and websockets to make what are, in the
end, four plain HTTP calls.

What it does that the rest of the codebase should not have to think about:

  * resolves credentials (runtime override -> environment -> .env)
  * uploads bytes and returns the SHA-256 **it computed over the bytes it sent**,
    so the digest in the audit record is measured rather than asserted
  * mints short-lived signed download URLs — the buckets are private, and a
    forensic deliverable must never sit behind a permanent public link
  * best-effort writes an audit row to `public.case_artifacts` when that table
    exists, and stays silent when it does not

Failure is never silent and never fabricated. Every error path raises a
StorageError carrying a message meant for the operator, and callers that can
degrade to local disk check `STORE.configured` first rather than catching.
"""

import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger("e-rakshak-storage")

#: PostgREST codes meaning "the audit table/columns are not there at all", as
#: opposed to "this particular row was rejected". Only these disable auditing;
#: everything else is a per-row problem and must not switch it off. See
#: `record_artifact` for why that distinction matters.
_SCHEMA_ABSENT_CODES = {
    "PGRST205",  # table not found in schema cache
    "PGRST204",  # column not found in schema cache
    "PGRST202",  # schema not exposed
}

#: Both buckets are created private. `case-reports` is mime-restricted to .docx
#: because nothing else is ever a deliverable; `case-evidence` accepts whatever
#: the operator ingests (xlsx / csv / pdf / json).
BUCKET_REPORTS = "case-reports"
BUCKET_EVIDENCE = "case-evidence"

#: Audit table. Optional — see `_record_artifact`. Kept out of the storage path
#: itself so a missing table degrades the feature to "files are safe but not
#: indexed" rather than breaking the upload.
ARTIFACT_TABLE = "case_artifacts"

#: Signed URLs are handed to a browser that follows the redirect immediately.
#: Ten minutes is generous for that round trip and short enough that a URL
#: pasted into a chat log stops working before it can be misused.
SIGNED_URL_TTL_SECONDS = 600

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 120

#: Anything outside this set is replaced in an object key. Supabase accepts a
#: fairly wide range, but a key containing a space or a quote is a support ticket
#: waiting to happen once it is embedded in a signed URL.
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._\-/]+")


class StorageError(RuntimeError):
    """Any failure talking to Supabase Storage. `status` is the HTTP status to surface."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


class StorageNotConfigured(StorageError):
    """No Supabase credentials available. Distinct so callers can fall back to disk."""

    def __init__(self, message="Supabase Storage is not configured."):
        super().__init__(message, status=503)


def _load_dotenv_value(*names):
    """
    Read a value out of a .env file without importing python-dotenv.

    Checked in order: repo root, then backend/. Same six-line parser as the
    copilot uses, for the same reason — enabling this should never turn into a
    dependency install.
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
                key, _, value = line.partition("=")
                if key.strip() in names:
                    value = value.strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            continue
    return None


def _safe_key(text, fallback="unnamed"):
    """Reduce arbitrary text to something safe to embed in an object key."""
    cleaned = _UNSAFE_KEY_CHARS.sub("_", str(text or "").strip()).strip("._-/")
    return cleaned or fallback


def new_case_id(now=None):
    """
    Mint a case identifier for a fresh investigation.

    Objects are namespaced under this, which is what stops a second run from
    overwriting the first run's deliverables and what makes "everything belonging
    to this case" a single prefix listing.

    The four random characters matter: the timestamp alone is only
    second-granular, so two resets inside the same second — trivially reachable
    from a script, a double-clicked button, or two operators on one server —
    would mint the same id and silently merge two investigations into one
    prefix, with the second overwriting the first's deliverables.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"CASE_{stamp}_{secrets.token_hex(2)}"


def report_path(case_id, entity_id, kind):
    """Object key for a generated deliverable. `kind` is 'forensic' or 'str'."""
    return f"{_safe_key(case_id, 'CASE_unknown')}/{_safe_key(kind, 'forensic')}/{_safe_key(entity_id, 'entity')}.docx"


def evidence_path(case_id, filename):
    """Object key for an ingested source file, preserving its original name."""
    return f"{_safe_key(case_id, 'CASE_unknown')}/{_safe_key(filename)}"


class SupabaseStore:
    """
    Stateless-per-call client. Instantiated once and held at module scope as
    `STORE`; `configure()` lets a deployment supply credentials at runtime.

    The key used here is the **secret** (service-role) key, which bypasses RLS.
    That is appropriate because this process is the trusted backend and the
    buckets are private — but it is also why the key must never be sent to the
    browser. Nothing in this module returns it, logs it, or embeds it in a URL.
    """

    def __init__(self, url=None, key=None):
        self._runtime_url = url
        self._runtime_key = key
        self._session = requests.Session()
        #: Set once the audit table is discovered to be absent, so a deployment
        #: without it does not pay a failed round trip on every single upload.
        self._artifact_table_missing = False
        #: {(bucket, path): sha256} of what this process last put at each key.
        #: The report endpoints re-upload on every download click, and clicking a
        #: download link twice re-sends an identical ~220 KB body for no reason;
        #: a digest match short-circuits that. Keyed by content, so a genuinely
        #: regenerated report with different bytes still uploads.
        self._uploaded_digests = {}

    # ── configuration ───────────────────────────────────────────────────────

    @property
    def url(self):
        raw = (
            self._runtime_url
            or os.getenv("SUPABASE_URL")
            or _load_dotenv_value("SUPABASE_URL")
        )
        return raw.rstrip("/") if raw else None

    @property
    def key(self):
        return (
            self._runtime_key
            or os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or _load_dotenv_value("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
        )

    @property
    def configured(self):
        return bool(self.url and self.key)

    def configure(self, url=None, key=None):
        """Supply credentials for this process. Held in memory only."""
        if url:
            self._runtime_url = url.rstrip("/")
        if key:
            self._runtime_key = key
        self._artifact_table_missing = False

    def key_fingerprint(self):
        """
        A short, non-reversible tag identifying which key is loaded.

        Lets an operator confirm the server picked up the credentials they meant
        without the key itself ever being displayed.
        """
        key = self.key
        if not key:
            return None
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def _headers(self, extra=None):
        key = self.key
        if not key:
            raise StorageNotConfigured()
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method, path, **kwargs):
        if not self.configured:
            raise StorageNotConfigured()
        try:
            return self._session.request(
                method,
                f"{self.url}{path}",
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                **kwargs,
            )
        except requests.RequestException as e:
            raise StorageError(f"Could not reach Supabase Storage: {e}") from e

    @staticmethod
    def _fail(response, action):
        """Turn a non-2xx response into a StorageError with a usable message."""
        detail = ""
        try:
            body = response.json()
            detail = body.get("message") or body.get("error") or ""
        except ValueError:
            detail = (response.text or "").strip()[:200]
        raise StorageError(
            f"{action} failed ({response.status_code}){f': {detail}' if detail else ''}",
            status=502,
        )

    # ── storage operations ──────────────────────────────────────────────────

    def upload(self, bucket, path, data, content_type="application/octet-stream"):
        """
        Upload bytes, overwriting any existing object at the same key.

        Upsert is deliberate: regenerating a report for the same entity in the
        same case should replace the stale deliverable, not accumulate a second
        copy that a later listing has to disambiguate.

        Returns {bucket, path, size_bytes, sha256, content_type}. The digest is
        computed here over the exact bytes sent — it is the chain-of-custody
        stamp for the stored object, so it is measured, never passed in.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise StorageError("upload() expects bytes.", status=500)
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()

        result = {
            "bucket": bucket,
            "path": path,
            "size_bytes": len(payload),
            "sha256": digest,
            "content_type": content_type,
        }

        if self._uploaded_digests.get((bucket, path)) == digest:
            return {**result, "skipped": True}

        self._put_object(bucket, path, payload, content_type)
        self._uploaded_digests[(bucket, path)] = digest
        return {**result, "skipped": False}

    def upload_file(self, bucket, path, file_path, content_type="application/octet-stream"):
        """
        Upload a file from disk without holding it in memory.

        The evidence path streams a browser upload to disk precisely so a large
        file never has to be resident; reading it straight back with
        `read_bytes()` to hand to `upload()` would undo that and put the whole
        thing — up to the bucket's 50 MB ceiling — back on the heap. Here the
        digest is taken in one chunked pass and the body is streamed in a second,
        so memory stays flat regardless of file size.
        """
        file_path = Path(file_path)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with open(file_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size_bytes += len(chunk)
        except OSError as e:
            raise StorageError(f"Could not read {file_path}: {e}", status=500) from e

        hexdigest = digest.hexdigest()
        result = {
            "bucket": bucket,
            "path": path,
            "size_bytes": size_bytes,
            "sha256": hexdigest,
            "content_type": content_type,
        }

        if self._uploaded_digests.get((bucket, path)) == hexdigest:
            return {**result, "skipped": True}

        try:
            with open(file_path, "rb") as handle:
                self._put_object(bucket, path, handle, content_type, size_bytes)
        except OSError as e:
            raise StorageError(f"Could not read {file_path}: {e}", status=500) from e

        self._uploaded_digests[(bucket, path)] = hexdigest
        return {**result, "skipped": False}

    def _put_object(self, bucket, path, body, content_type, content_length=None):
        """PUT the bytes. `body` is either a bytes payload or a file object to stream."""
        headers = {
            "Content-Type": content_type,
            # Without this a repeat upload to the same key returns 409.
            "x-upsert": "true",
        }
        if content_length is not None:
            # A file object has no implicit length, and without this requests
            # falls back to chunked transfer encoding, which the storage API
            # rejects for uploads.
            headers["Content-Length"] = str(content_length)

        response = self._request(
            "POST",
            f"/storage/v1/object/{bucket}/{path}",
            headers=self._headers(headers),
            data=body,
        )
        if not response.ok:
            self._fail(response, f"Upload to {bucket}/{path}")
        return response

    def signed_url(self, bucket, path, expires_in=SIGNED_URL_TTL_SECONDS, download_name=None):
        """
        Mint a time-limited download URL for a private object.

        `download_name` sets the filename the browser saves as. Without it the
        object key's last segment is used, which would hand the investigator a
        file named after the entity id with no indication of which report it is.
        """
        response = self._request(
            "POST",
            f"/storage/v1/object/sign/{bucket}/{path}",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"expiresIn": int(expires_in)},
        )
        if not response.ok:
            self._fail(response, f"Signing {bucket}/{path}")

        try:
            signed = response.json()["signedURL"]
        except (ValueError, KeyError) as e:
            raise StorageError("Supabase returned no signed URL.") from e

        url = f"{self.url}/storage/v1{signed}"
        if download_name:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}download={requests.utils.quote(download_name)}"
        return url

    def exists(self, bucket, path):
        """Whether an object is present. Used to skip a needless regeneration."""
        response = self._request(
            "HEAD", f"/storage/v1/object/{bucket}/{path}", headers=self._headers()
        )
        return response.status_code == 200

    def list_prefix(self, bucket, prefix="", limit=100):
        """List objects under a prefix — i.e. everything belonging to one case."""
        response = self._request(
            "POST",
            f"/storage/v1/object/list/{bucket}",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"prefix": prefix, "limit": int(limit),
                  "sortBy": {"column": "created_at", "order": "desc"}},
        )
        if not response.ok:
            self._fail(response, f"Listing {bucket}/{prefix}")
        try:
            return response.json()
        except ValueError:
            return []

    def remove(self, bucket, paths):
        """Delete objects by key. Used by the case-reset path."""
        keys = [paths] if isinstance(paths, str) else list(paths)
        if not keys:
            return []
        response = self._request(
            "DELETE",
            f"/storage/v1/object/{bucket}",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"prefixes": keys},
        )
        if not response.ok:
            self._fail(response, f"Deleting from {bucket}")

        # Drop these keys from the upload cache. Without this, deleting an object
        # and then re-uploading byte-identical content would match the remembered
        # digest, skip the request, and leave the object permanently missing while
        # reporting success.
        for key in keys:
            self._uploaded_digests.pop((bucket, key), None)

        try:
            return response.json()
        except ValueError:
            return []

    # ── audit index (optional) ──────────────────────────────────────────────

    def record_artifact(self, case_id, kind, filename, stored, entity_id=None):
        """
        Append an audit row describing a stored artefact.

        Best-effort by design: `supabase_schema.sql` creates the table, but a
        deployment that has not run it still gets working storage — the files are
        safe either way, they are simply not queryable by case until the table
        exists. A failure here must never turn a successful upload into an error
        the operator sees.

        Two failure modes are deliberately NOT treated alike:

          schema absent (PGRST205/204/202) — the table was never created. Stop
            trying for the rest of the process; there is nothing to retry against.

          row rejected (anything else) — a constraint violation, an oversized
            field, a transient network fault. Log it and carry on WITH AUDITING
            STILL ENABLED.

        Collapsing the second case into the first is a real hazard: a single bad
        row would silently switch off the audit trail for the whole process, so
        every later artefact would be stored with no record of it ever having
        been made. On a chain-of-custody log, failing quiet and staying failed is
        the worst available behaviour — hence the split, and hence the logging.
        """
        if self._artifact_table_missing or not self.configured:
            return None

        row = {
            "case_id": case_id,
            "kind": kind,
            "entity_id": entity_id,
            "filename": filename,
            "bucket": stored["bucket"],
            "storage_path": stored["path"],
            "size_bytes": stored["size_bytes"],
            "sha256": stored["sha256"],
            "content_type": stored.get("content_type"),
        }
        try:
            response = self._request(
                "POST",
                f"/rest/v1/{ARTIFACT_TABLE}",
                headers=self._headers({
                    "Content-Type": "application/json",
                    # Upsert on storage_path so regenerating a report updates the
                    # existing audit row rather than duplicating it.
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                }),
                data=json.dumps(row),
            )
        except StorageError as e:
            logger.warning(f"Audit row not written for {stored['path']}: {e}")
            return False

        if response.ok:
            return True

        code = ""
        message = ""
        try:
            body = response.json()
            code = body.get("code") or ""
            message = body.get("message") or ""
        except ValueError:
            message = (response.text or "").strip()[:200]

        if code in _SCHEMA_ABSENT_CODES:
            self._artifact_table_missing = True
            logger.info(
                f"Audit table public.{ARTIFACT_TABLE} not present ({code}); artefacts "
                f"will be stored without an index. Run backend/storage/supabase_schema.sql "
                f"to enable it."
            )
            return None

        # A rejected row. Loud, because an artefact now exists in storage with no
        # audit record of it — and auditing stays on so the next one still lands.
        logger.error(
            f"Audit row REJECTED for {stored['path']} "
            f"({response.status_code}{f' {code}' if code else ''}): {message}"
        )
        return False


#: Process-wide instance. Import this rather than constructing your own, so a
#: runtime `configure()` call is visible everywhere.
STORE = SupabaseStore()
