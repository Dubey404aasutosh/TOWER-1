"""
Durable artefact storage for case deliverables.

The pipeline writes reports and receives evidence files onto local disk. That is
correct for a workstation and wrong for a hosted deployment: on Heroku, Railway,
Render, Fly, Lambda or any container without a mounted volume the filesystem is
ephemeral, so every generated .docx disappears on the next restart or redeploy.
An investigator who comes back an hour later finds their report gone.

This package moves those artefacts into Supabase Storage, keyed by case, with a
SHA-256 recorded for each one. It is entirely optional: with no credentials
configured every call reports "not configured" and the callers fall back to the
existing on-disk behaviour unchanged.
"""

from .supabase_store import (
    STORE,
    SupabaseStore,
    StorageError,
    StorageNotConfigured,
    BUCKET_REPORTS,
    BUCKET_EVIDENCE,
    new_case_id,
    report_path,
    evidence_path,
)

__all__ = [
    "STORE",
    "SupabaseStore",
    "StorageError",
    "StorageNotConfigured",
    "BUCKET_REPORTS",
    "BUCKET_EVIDENCE",
    "new_case_id",
    "report_path",
    "evidence_path",
]
