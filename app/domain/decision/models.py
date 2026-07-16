"""Immutable domain types for the program registry."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegistryValidationError(ValueError):
    """Raised when a program registry contract is invalid."""


class ProgramId(str, Enum):
    """Canonical program identifiers."""

    SUMMER_CAMP = "summer_camp"
    SUNDAY_SCHOOL = "sunday_school"
    ADULT_EVENTS = "adult_events"


def _validate_exact_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise RegistryValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise RegistryValidationError(f"{field_name} must not contain outer whitespace")


@dataclass(frozen=True, slots=True)
class RegistryAlias:
    """An exact, already-canonical alias for one program."""

    value: str
    program_id: ProgramId

    def __post_init__(self) -> None:
        _validate_exact_text(self.value, "alias")
        if not isinstance(self.program_id, ProgramId):
            raise RegistryValidationError("alias program_id is unsupported")


@dataclass(frozen=True, slots=True)
class SymbolicOwnerReference:
    """A symbolic reference to an existing owner, never a runtime object."""

    value: str

    def __post_init__(self) -> None:
        _validate_exact_text(self.value, "owner reference")


@dataclass(frozen=True, slots=True)
class ProgramOwnerReferences:
    """Symbolic source owners associated with a program."""

    lifecycle_owner: SymbolicOwnerReference | None = None
    facts_owner: SymbolicOwnerReference | None = None
    approved_copy_namespace: SymbolicOwnerReference | None = None
    configuration_owner: SymbolicOwnerReference | None = None

    def __post_init__(self) -> None:
        for value in (
            self.lifecycle_owner,
            self.facts_owner,
            self.approved_copy_namespace,
            self.configuration_owner,
        ):
            if value is not None and not isinstance(value, SymbolicOwnerReference):
                raise RegistryValidationError(
                    "program owners must be symbolic owner references or None"
                )


@dataclass(frozen=True, slots=True)
class ProgramDefinition:
    """Stable program identity and symbolic ownership metadata."""

    program_id: ProgramId
    canonical_name: str
    aliases: tuple[RegistryAlias, ...]
    owners: ProgramOwnerReferences

    def __post_init__(self) -> None:
        if not isinstance(self.program_id, ProgramId):
            raise RegistryValidationError("program_id is unsupported")
        _validate_exact_text(self.canonical_name, "canonical_name")
        if self.canonical_name != self.program_id.value:
            raise RegistryValidationError(
                "canonical_name must equal the canonical program_id value"
            )
        if not isinstance(self.aliases, tuple):
            raise RegistryValidationError("aliases must be an immutable tuple")
        if not all(isinstance(alias, RegistryAlias) for alias in self.aliases):
            raise RegistryValidationError("aliases must contain RegistryAlias values")
        if not isinstance(self.owners, ProgramOwnerReferences):
            raise RegistryValidationError(
                "owners must be ProgramOwnerReferences"
            )
