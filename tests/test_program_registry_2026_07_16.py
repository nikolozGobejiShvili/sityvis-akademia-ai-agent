from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.domain.decision import (
    PROGRAM_REGISTRY,
    ProgramDefinition,
    ProgramId,
    ProgramOwnerReferences,
    ProgramRegistry,
    RegistryAlias,
    RegistryValidationError,
    SymbolicOwnerReference,
)


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "app" / "domain" / "decision"


def _owners() -> ProgramOwnerReferences:
    return ProgramOwnerReferences(
        lifecycle_owner=SymbolicOwnerReference("owner.lifecycle"),
        facts_owner=SymbolicOwnerReference("owner.facts"),
        configuration_owner=SymbolicOwnerReference("owner.configuration"),
    )


def _definition(
    program_id: ProgramId,
    *extra_aliases: str,
) -> ProgramDefinition:
    return ProgramDefinition(
        program_id=program_id,
        canonical_name=program_id.value,
        aliases=tuple(
            RegistryAlias(alias, program_id)
            for alias in (program_id.value, *extra_aliases)
        ),
        owners=_owners(),
    )


def _complete_definitions(
    replacements: dict[ProgramId, ProgramDefinition] | None = None,
) -> tuple[ProgramDefinition, ...]:
    replacements = replacements or {}
    return tuple(
        replacements.get(program_id, _definition(program_id))
        for program_id in ProgramId
    )


def test_program_ids_are_exactly_the_three_canonical_values():
    assert tuple(ProgramId) == (
        ProgramId.SUMMER_CAMP,
        ProgramId.SUNDAY_SCHOOL,
        ProgramId.ADULT_EVENTS,
    )
    assert tuple(item.value for item in ProgramId) == (
        "summer_camp",
        "sunday_school",
        "adult_events",
    )


def test_registry_is_complete_and_has_deterministic_order():
    assert tuple(item.program_id for item in PROGRAM_REGISTRY.all()) == tuple(
        ProgramId
    )
    assert PROGRAM_REGISTRY.definitions is PROGRAM_REGISTRY.all()
    assert len(PROGRAM_REGISTRY.all()) == 3


def test_registry_models_and_public_collections_are_immutable():
    definition = PROGRAM_REGISTRY.get(ProgramId.SUMMER_CAMP)
    assert definition is not None
    alias = definition.aliases[0]
    owner = definition.owners.lifecycle_owner
    assert owner is not None

    with pytest.raises(FrozenInstanceError):
        definition.canonical_name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        alias.value = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        owner.value = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        definition.owners.lifecycle_owner = None  # type: ignore[misc]
    with pytest.raises(AttributeError):
        definition.aliases.append(alias)  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        PROGRAM_REGISTRY.definitions = ()  # type: ignore[misc]


def test_exact_program_id_lookup_returns_definition_and_unknown_is_none():
    for program_id in ProgramId:
        definition = PROGRAM_REGISTRY.get(program_id)
        assert definition is not None
        assert definition.program_id is program_id

    assert PROGRAM_REGISTRY.get("unknown") is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("summer_camp", ProgramId.SUMMER_CAMP),
        ("sunday_school", ProgramId.SUNDAY_SCHOOL),
        ("adult_events", ProgramId.ADULT_EVENTS),
    ],
)
def test_exact_canonical_alias_lookup(alias: str, expected: ProgramId):
    definition = PROGRAM_REGISTRY.find_by_alias(alias)
    assert definition is not None
    assert definition.program_id is expected


@pytest.mark.parametrize(
    "alias",
    [
        "unknown_program",
        "SUMMER_CAMP",
        " summer_camp",
        "summer_camp ",
        "summer-camp",
        "summer",
        "camp",
        "summer_camp_registration",
    ],
)
def test_alias_lookup_does_not_normalize_guess_or_match_substrings(alias: str):
    assert PROGRAM_REGISTRY.find_by_alias(alias) is None


def test_duplicate_program_id_fails_clearly():
    definitions = (
        _definition(ProgramId.SUMMER_CAMP),
        _definition(ProgramId.SUMMER_CAMP),
        _definition(ProgramId.SUNDAY_SCHOOL),
        _definition(ProgramId.ADULT_EVENTS),
    )
    with pytest.raises(RegistryValidationError, match="duplicate program IDs"):
        ProgramRegistry(definitions)


def test_duplicate_alias_within_one_program_fails_clearly():
    duplicate = ProgramDefinition(
        program_id=ProgramId.SUMMER_CAMP,
        canonical_name=ProgramId.SUMMER_CAMP.value,
        aliases=(
            RegistryAlias("summer_camp", ProgramId.SUMMER_CAMP),
            RegistryAlias("summer_camp", ProgramId.SUMMER_CAMP),
        ),
        owners=_owners(),
    )
    definitions = _complete_definitions({ProgramId.SUMMER_CAMP: duplicate})
    with pytest.raises(RegistryValidationError, match="duplicate aliases"):
        ProgramRegistry(definitions)


def test_duplicate_alias_across_programs_fails_clearly():
    definitions = _complete_definitions(
        {
            ProgramId.SUMMER_CAMP: _definition(
                ProgramId.SUMMER_CAMP, "shared_program"
            ),
            ProgramId.SUNDAY_SCHOOL: _definition(
                ProgramId.SUNDAY_SCHOOL, "shared_program"
            ),
        }
    )
    with pytest.raises(
        RegistryValidationError,
        match="aliases assigned to multiple programs",
    ):
        ProgramRegistry(definitions)


@pytest.mark.parametrize("alias", ["", "   ", " leading", "trailing "])
def test_invalid_alias_is_rejected(alias: str):
    with pytest.raises(RegistryValidationError):
        RegistryAlias(alias, ProgramId.SUMMER_CAMP)


def test_alias_must_belong_to_its_definition():
    definition = ProgramDefinition(
        program_id=ProgramId.SUMMER_CAMP,
        canonical_name=ProgramId.SUMMER_CAMP.value,
        aliases=(
            RegistryAlias("summer_camp", ProgramId.SUMMER_CAMP),
            RegistryAlias("wrong_owner", ProgramId.SUNDAY_SCHOOL),
        ),
        owners=_owners(),
    )
    with pytest.raises(RegistryValidationError, match="does not match"):
        ProgramRegistry(
            _complete_definitions({ProgramId.SUMMER_CAMP: definition})
        )


@pytest.mark.parametrize("value", ["", "   ", " owner", "owner "])
def test_invalid_symbolic_owner_reference_is_rejected(value: str):
    with pytest.raises(RegistryValidationError):
        SymbolicOwnerReference(value)


def test_optional_owner_references_accept_none():
    assert ProgramOwnerReferences() == ProgramOwnerReferences(
        lifecycle_owner=None,
        facts_owner=None,
        approved_copy_namespace=None,
        configuration_owner=None,
    )


def test_owner_references_reject_untyped_runtime_values():
    with pytest.raises(RegistryValidationError, match="symbolic"):
        ProgramOwnerReferences(
            lifecycle_owner="owner.lifecycle",  # type: ignore[arg-type]
        )


def test_unsupported_program_id_and_mutable_alias_collection_are_rejected():
    with pytest.raises(RegistryValidationError, match="unsupported"):
        ProgramDefinition(
            program_id="other",  # type: ignore[arg-type]
            canonical_name="other",
            aliases=(),
            owners=_owners(),
        )

    with pytest.raises(RegistryValidationError, match="immutable tuple"):
        ProgramDefinition(
            program_id=ProgramId.SUMMER_CAMP,
            canonical_name=ProgramId.SUMMER_CAMP.value,
            aliases=[],  # type: ignore[arg-type]
            owners=_owners(),
        )


def test_registry_contains_only_stable_identity_and_symbolic_owner_fields():
    assert {field.name for field in fields(ProgramDefinition)} == {
        "program_id",
        "canonical_name",
        "aliases",
        "owners",
    }
    assert {field.name for field in fields(ProgramOwnerReferences)} == {
        "lifecycle_owner",
        "facts_owner",
        "approved_copy_namespace",
        "configuration_owner",
    }

    strings: list[str] = []
    for definition in PROGRAM_REGISTRY.all():
        strings.append(definition.canonical_name)
        strings.extend(alias.value for alias in definition.aliases)
        for owner in (
            definition.owners.lifecycle_owner,
            definition.owners.facts_owner,
            definition.owners.approved_copy_namespace,
            definition.owners.configuration_owner,
        ):
            if owner is not None:
                strings.append(owner.value)

    assert all("http" not in value and "@" not in value for value in strings)
    assert all(
        not any(character.isdigit() for character in value)
        for value in strings
    )
    assert all(
        not any("\u10a0" <= character <= "\u10ff" for character in value)
        for value in strings
    )


def test_domain_package_has_no_forbidden_dependencies():
    forbidden_prefixes = (
        "app.agent",
        "app.flows",
        "app.services",
        "openai",
        "redis",
        "gspread",
        "google",
        "twilio",
    )
    forbidden_fragments = (
        "approved_copy",
        "calendar",
        "notification",
        "prompt",
        "sheets",
    )

    for path in sorted(DOMAIN_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        for module in imported:
            assert not module.startswith(forbidden_prefixes), (path, module)
            assert not any(
                fragment in module for fragment in forbidden_fragments
            ), (path, module)


def test_domain_package_import_is_side_effect_free_without_environment():
    command = (
        "import sys; "
        "import app.domain.decision as decision; "
        "assert len(decision.PROGRAM_REGISTRY.all()) == 3; "
        "assert not any(name.startswith(('app.services', 'app.flows')) "
        "for name in sys.modules)"
    )
    system_root = str(Path(Path(sys.executable).anchor) / "Windows")
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "SYSTEMROOT": system_root,
            "WINDIR": system_root,
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_conflict_validation_is_independent_of_definition_order():
    definitions = _complete_definitions(
        {
            ProgramId.SUMMER_CAMP: _definition(
                ProgramId.SUMMER_CAMP, "shared"
            ),
            ProgramId.ADULT_EVENTS: _definition(
                ProgramId.ADULT_EVENTS, "shared"
            ),
        }
    )
    messages = []
    for supplied in (definitions, tuple(reversed(definitions))):
        with pytest.raises(RegistryValidationError) as exc_info:
            ProgramRegistry(supplied)
        messages.append(str(exc_info.value))
    assert messages[0] == messages[1]
