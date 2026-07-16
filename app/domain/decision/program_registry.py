"""Immutable, exact-match registry for canonical program identities."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import (
    ProgramDefinition,
    ProgramId,
    ProgramOwnerReferences,
    RegistryAlias,
    RegistryValidationError,
    SymbolicOwnerReference,
)


@dataclass(frozen=True, slots=True)
class ProgramRegistry:
    """Validated registry with deterministic canonical ordering."""

    definitions: tuple[ProgramDefinition, ...]

    def __init__(self, definitions: Iterable[ProgramDefinition]) -> None:
        try:
            supplied = tuple(definitions)
        except TypeError as exc:
            raise RegistryValidationError(
                "registry definitions must be iterable"
            ) from exc

        if not all(isinstance(item, ProgramDefinition) for item in supplied):
            raise RegistryValidationError(
                "registry definitions must contain ProgramDefinition values"
            )

        id_counts = Counter(item.program_id for item in supplied)
        duplicate_ids = sorted(
            program_id.value
            for program_id, count in id_counts.items()
            if count > 1
        )
        if duplicate_ids:
            raise RegistryValidationError(
                f"duplicate program IDs: {', '.join(duplicate_ids)}"
            )

        expected_ids = set(ProgramId)
        actual_ids = set(id_counts)
        missing_ids = sorted(item.value for item in expected_ids - actual_ids)
        extra_ids = sorted(
            str(item) for item in actual_ids if item not in expected_ids
        )
        if missing_ids or extra_ids:
            details = []
            if missing_ids:
                details.append(f"missing: {', '.join(missing_ids)}")
            if extra_ids:
                details.append(f"unsupported: {', '.join(extra_ids)}")
            raise RegistryValidationError(
                f"registry must define every canonical program ({'; '.join(details)})"
            )

        alias_owners: dict[str, set[ProgramId]] = {}
        for definition in supplied:
            alias_values = [alias.value for alias in definition.aliases]
            duplicate_aliases = sorted(
                alias
                for alias, count in Counter(alias_values).items()
                if count > 1
            )
            if duplicate_aliases:
                raise RegistryValidationError(
                    "duplicate aliases for "
                    f"{definition.program_id.value}: {', '.join(duplicate_aliases)}"
                )

            mismatched = sorted(
                alias.value
                for alias in definition.aliases
                if alias.program_id is not definition.program_id
            )
            if mismatched:
                raise RegistryValidationError(
                    "alias program_id does not match its definition: "
                    f"{', '.join(mismatched)}"
                )

            canonical_alias = definition.program_id.value
            if canonical_alias not in alias_values:
                raise RegistryValidationError(
                    f"{definition.program_id.value} is missing its canonical alias"
                )

            for alias in alias_values:
                alias_owners.setdefault(alias, set()).add(definition.program_id)

        cross_program_conflicts = sorted(
            alias
            for alias, owners in alias_owners.items()
            if len(owners) > 1
        )
        if cross_program_conflicts:
            raise RegistryValidationError(
                "aliases assigned to multiple programs: "
                f"{', '.join(cross_program_conflicts)}"
            )

        by_id = {definition.program_id: definition for definition in supplied}
        ordered = tuple(by_id[program_id] for program_id in ProgramId)
        object.__setattr__(self, "definitions", ordered)

    def get(self, program_id: ProgramId) -> ProgramDefinition | None:
        """Return the exact typed program definition, or None."""

        if not isinstance(program_id, ProgramId):
            return None
        return next(
            (
                definition
                for definition in self.definitions
                if definition.program_id is program_id
            ),
            None,
        )

    def find_by_alias(self, alias: str) -> ProgramDefinition | None:
        """Return an exact alias match without normalization or guessing."""

        if not isinstance(alias, str):
            return None
        for definition in self.definitions:
            if any(item.value == alias for item in definition.aliases):
                return definition
        return None

    def all(self) -> tuple[ProgramDefinition, ...]:
        """Return definitions in ProgramId declaration order."""

        return self.definitions


def _owner(value: str) -> SymbolicOwnerReference:
    return SymbolicOwnerReference(value)


PROGRAM_REGISTRY = ProgramRegistry(
    (
        ProgramDefinition(
            program_id=ProgramId.SUMMER_CAMP,
            canonical_name=ProgramId.SUMMER_CAMP.value,
            aliases=(
                RegistryAlias(
                    ProgramId.SUMMER_CAMP.value,
                    ProgramId.SUMMER_CAMP,
                ),
            ),
            owners=ProgramOwnerReferences(
                lifecycle_owner=_owner(
                    "app.services.admin_config_service.get_camp_status"
                ),
                facts_owner=_owner(
                    "app.services.admin_config_service.get_camp_facts"
                ),
                approved_copy_namespace=_owner("programs.camp"),
                configuration_owner=_owner(
                    "data.admin_config.sections.summer_camp"
                ),
            ),
        ),
        ProgramDefinition(
            program_id=ProgramId.SUNDAY_SCHOOL,
            canonical_name=ProgramId.SUNDAY_SCHOOL.value,
            aliases=(
                RegistryAlias(
                    ProgramId.SUNDAY_SCHOOL.value,
                    ProgramId.SUNDAY_SCHOOL,
                ),
            ),
            owners=ProgramOwnerReferences(
                lifecycle_owner=_owner(
                    "app.services.admin_config_service.get_sunday_school_status"
                ),
                facts_owner=_owner(
                    "app.services.admin_config_service.get_sunday_school_status"
                ),
                approved_copy_namespace=None,
                configuration_owner=_owner(
                    "data.admin_config.sections.sunday_school"
                ),
            ),
        ),
        ProgramDefinition(
            program_id=ProgramId.ADULT_EVENTS,
            canonical_name=ProgramId.ADULT_EVENTS.value,
            aliases=(
                RegistryAlias(
                    ProgramId.ADULT_EVENTS.value,
                    ProgramId.ADULT_EVENTS,
                ),
            ),
            owners=ProgramOwnerReferences(
                lifecycle_owner=_owner(
                    "app.services.admin_config_service.get_active_adult_events"
                ),
                facts_owner=_owner(
                    "app.services.admin_config_service.get_adult_events"
                ),
                approved_copy_namespace=None,
                configuration_owner=_owner(
                    "data.admin_config.sections.adult_events"
                ),
            ),
        ),
    )
)
