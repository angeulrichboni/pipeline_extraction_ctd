"""Mapping CTD vers ICD-10 (OMS, release 2019) fondé sur une référence auditée."""

from .engine import apply_mapping
from .reference import load_reference, validate_reference

__all__ = [
    "apply_mapping", "load_reference", "validate_reference",
]
