-- E-RAKSHAK — Supabase audit index for stored case artefacts
-- ============================================================================
-- Run this once in the Supabase SQL editor:
--   Dashboard -> SQL Editor -> New query -> paste -> Run
--
-- This table is OPTIONAL. Storage works without it — reports and evidence still
-- upload, and each object still carries the SHA-256 computed at upload time.
-- What the table adds is the ability to ASK questions of the archive:
--
--   "every deliverable produced for CASE_20260811_143000"
--   "which evidence file did this report's findings come from"
--   "has the .docx we handed the court been replaced since"
--
-- Without it, `backend/storage/supabase_store.py` detects the absence on its
-- first write, stops trying, and carries on storing files.

create table if not exists public.case_artifacts (
    id            uuid primary key default gen_random_uuid(),

    -- Namespaces one investigation. Matches the object key prefix in storage.
    case_id       text not null,

    -- What this artefact is. Constrained rather than free text so a typo cannot
    -- quietly create a fourth category that no query looks for.
    kind          text not null check (kind in ('forensic_report', 'str_report', 'evidence')),

    -- Null for evidence files, which belong to the case rather than an entity.
    entity_id     text,

    filename      text not null,
    bucket        text not null,

    -- Unique: one row per stored object. Regenerating a report upserts this row
    -- instead of appending a second one describing the same key.
    storage_path  text not null unique,

    size_bytes    bigint not null,

    -- Measured by hashlib over the exact bytes uploaded. This is the Sec 65B
    -- chain-of-custody stamp: compare it against the file a court holds to prove
    -- the deliverable has not been altered since it left this system.
    sha256        text not null,

    content_type  text,
    created_at    timestamptz not null default now()
);

create index if not exists case_artifacts_case_id_idx  on public.case_artifacts (case_id, created_at desc);
create index if not exists case_artifacts_entity_id_idx on public.case_artifacts (entity_id);
create index if not exists case_artifacts_sha256_idx    on public.case_artifacts (sha256);

-- RLS on, with no policy granted to anon/authenticated.
--
-- The backend talks to this table with the SECRET (service-role) key, which
-- bypasses RLS. Every other caller — notably anything holding the publishable
-- key, which is by definition shipped to browsers — is denied. Case artefact
-- metadata names entities and evidence files in live investigations; it should
-- never be readable from a client.
alter table public.case_artifacts enable row level security;

-- Storage object access is governed the same way: both buckets are created
-- private, so objects are reachable only through a short-lived signed URL minted
-- by the backend. No storage.objects policy is granted here on purpose.
