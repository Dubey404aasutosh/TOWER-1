"""
Canonical Event and Entity schema — the contract every parser must output.
All downstream processing operates on these dataclasses, never on raw file formats.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """Single normalized event from any source (bank/CDR/IPDR)."""
    entity_ref: str                     # Raw identifier from source (phone/account/MSISDN)
    event_type: str                     # "call" | "sms" | "ip_session" | "transaction"
    timestamp: datetime                 # Event start time (normalized to datetime)
    end_timestamp: Optional[datetime] = None   # For IP sessions / call duration
    amount: Optional[float] = None             # Transactions only (positive = credit, negative = debit)
    counterparty: Optional[str] = None         # B-party phone, beneficiary account, dest IP
    location: Optional[str] = None             # Cell ID / IP geolocation
    source_file: str = ""                      # Provenance — which raw file this came from
    raw_row_ref: int = 0                       # Row index in original file for audit trail
    utr: Optional[str] = None                  # Unique Transaction Reference (bank only)
    channel: Optional[str] = None              # UPI/IMPS/NEFT/RTGS (bank only)
    direction: Optional[str] = None            # "credit"/"debit" for bank; "incoming"/"outgoing" for calls
    imei: Optional[str] = None                 # IMEI from CDR
    entity_id: Optional[str] = None            # Resolved entity ID (set after entity resolution)


@dataclass
class Entity:
    """Resolved identity — one real person/suspect across all data sources."""
    entity_id: str
    raw_identifiers: dict = field(default_factory=lambda: {
        "phones": [],
        "accounts": [],
        "ips": [],
        "imeis": [],
        "vpas": [],
    })
    name: Optional[str] = None
    risk_tier: str = "LOW"
    ml_anomaly: bool = False
    rules_fired: list = field(default_factory=list)
