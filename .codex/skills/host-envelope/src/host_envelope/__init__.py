# Host-safe projector: skill stdout -> WorkBuddy HostToolReturn JSON.
from host_envelope.project import project_host_return, rejected_envelope, unwrap_skill_payload
from host_envelope.schema import SCHEMA_VERSION, validate_envelope

__all__ = [
    "SCHEMA_VERSION",
    "project_host_return",
    "rejected_envelope",
    "unwrap_skill_payload",
    "validate_envelope",
]
