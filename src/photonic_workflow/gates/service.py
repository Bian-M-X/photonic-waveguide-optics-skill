from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.models import GateName, GateRecord, GateStatus, Validity
from photonic_workflow.models.io import (
    atomic_write_text,
    contract_payload,
    parse_contract,
    revalidate_internal,
)

GATE_DEFINITIONS: dict[GateName, dict[str, Any]] = {
    GateName.G0: {
        "name": "device-contract",
        "requires": ["topology", "ports", "band", "stack", "modes", "metrics", "tolerances", "claim"],
        "applies_when": "any project-backed design, validation, optimization, or delivery claim is advanced",
        "allows_not_applicable": False,
    },
    GateName.G1: {
        "name": "port-and-straight-waveguide-baseline",
        "requires": [
            "mode-identity",
            "orientation",
            "normalization",
            "reference-planes",
            "exterior-partition",
            "source-basis",
            "mesh-boundary-sensitivity",
            "per-input-power",
            "driven-field-audit",
        ],
        "applies_when": "a claim relies on solver ports, propagated modes, or a driven wave solution",
        "allows_not_applicable": True,
    },
    GateName.G2: {
        "name": "component-qualification",
        "requires": [
            "complete-complex-s",
            "mode-labels",
            "passivity-or-gain-budget",
            "reciprocity-class",
            "per-input-energy",
            "geometry-and-model-level",
            "convergence",
            "validity-envelope",
            "field-sanity",
        ],
        "applies_when": "a component is promoted for reuse or quantitative engineering use",
        "allows_not_applicable": True,
    },
    GateName.G3: {
        "name": "assembly-contract",
        "requires": ["instances", "connections", "port-occupancy", "mode-match", "shared-grid", "conventions"],
        "applies_when": "two or more qualified blocks are composed into a circuit or netlist",
        "allows_not_applicable": True,
    },
    GateName.G4: {
        "name": "circuit-behavior",
        "requires": [
            "external-s",
            "singular-value-or-gain-budget",
            "reciprocity-class",
            "per-input-energy",
            "sampling",
            "sensitivity",
        ],
        "applies_when": "a composed circuit response is claimed over a declared band or corner set",
        "allows_not_applicable": True,
    },
    GateName.G5: {
        "name": "layout-and-connectivity",
        "requires": [
            "port-aware-layout",
            "extracted-netlist",
            "drc-or-declared-surrogate",
            "pdk-version",
            "routing-rules",
        ],
        "applies_when": "layout, connectivity, DRC, or tapeout readiness is claimed",
        "allows_not_applicable": True,
    },
    GateName.G6: {
        "name": "promoted-full-wave-subassembly",
        "requires": ["reference-plane-parity", "mode-parity", "complex-comparison", "tolerance", "root-cause"],
        "applies_when": "a circuit or reduced model is promoted by a higher-fidelity full-wave comparison",
        "allows_not_applicable": True,
    },
    GateName.G7: {
        "name": "robustness-and-optimization",
        "requires": [
            "baseline",
            "objective",
            "constraints",
            "checkpoint-policy",
            "solver-noise",
            "corners",
            "manufacturability-when-claimed",
            "high-fidelity-reevaluation",
        ],
        "applies_when": "an optimization winner, robustness result, or manufacturability claim is promoted",
        "allows_not_applicable": True,
    },
    GateName.G8: {
        "name": "evidence-package",
        "requires": ["source", "manifests", "logs", "tables", "plots", "ledger", "limitations", "next-action"],
        "applies_when": "a formal handoff, publication, tapeout package, or final evidence package is delivered",
        "allows_not_applicable": False,
    },
    GateName.M0: {
        "name": "test-ready",
        "requires": ["test-plan", "packaging-interface", "instrument-aliases", "safety-limits"],
        "applies_when": "the measurement track is activated",
        "allows_not_applicable": False,
    },
    GateName.M1: {
        "name": "raw-data-integrity",
        "requires": ["immutable-raw-data", "hashes", "setup-metadata", "analysis-link"],
        "applies_when": "measurement data is captured",
        "allows_not_applicable": False,
    },
    GateName.M2: {
        "name": "calibrated-measurement",
        "requires": ["calibration", "uncertainty", "processed-data-provenance"],
        "applies_when": "a calibrated measurement is claimed",
        "allows_not_applicable": False,
    },
    GateName.M3: {
        "name": "simulation-measurement-correlation",
        "requires": ["device-identity", "reference-plane-alignment", "common-metrics", "residuals"],
        "applies_when": "simulation-to-measurement correlation is claimed",
        "allows_not_applicable": True,
    },
    GateName.M4: {
        "name": "compact-model-recalibrated",
        "requires": ["fit-provenance", "fit-error", "validity-envelope", "release-record"],
        "applies_when": "a recalibrated compact model is released",
        "allows_not_applicable": True,
    },
}

GATE_PROFILES: dict[str, tuple[GateName, ...]] = {
    "component": (GateName.G0, GateName.G1, GateName.G2),
    "circuit": tuple(GateName(f"G{index}") for index in range(5)),
    "layout-tapeout": tuple(GateName(f"G{index}") for index in range(6)),
    "promoted-full-wave-overlay": (GateName.G6,),
    "optimization-robustness-overlay": (GateName.G7,),
    "delivery-overlay": (GateName.G8,),
    "measurement": (GateName.M0, GateName.M1, GateName.M2),
    "correlation": (GateName.M0, GateName.M1, GateName.M2, GateName.M3),
    "recalibration": tuple(GateName(f"M{index}") for index in range(5)),
}

_PROFILE_REQUIRED_PASS: dict[str, frozenset[GateName]] = {
    "component": frozenset({GateName.G0, GateName.G2}),
    "circuit": frozenset({GateName.G0, GateName.G2, GateName.G3, GateName.G4}),
    "layout-tapeout": frozenset(
        {GateName.G0, GateName.G2, GateName.G3, GateName.G4, GateName.G5}
    ),
    "promoted-full-wave-overlay": frozenset({GateName.G6}),
    "optimization-robustness-overlay": frozenset({GateName.G7}),
    "delivery-overlay": frozenset({GateName.G8}),
    "measurement": frozenset({GateName.M0, GateName.M1, GateName.M2}),
    "correlation": frozenset({GateName.M0, GateName.M1, GateName.M2, GateName.M3}),
    "recalibration": frozenset(GateName(f"M{index}") for index in range(5)),
}

_OVERLAY_PROFILES = {
    "promoted-full-wave-overlay",
    "optimization-robustness-overlay",
    "delivery-overlay",
}

_ACCEPTED_GATE_STATUSES = {GateStatus.PASS, GateStatus.NOT_APPLICABLE}
_DIGEST_PREFIX = "sha256:"


class GateLedger:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.path = self.project_root / "verification" / "gates.json"

    def default_records(self) -> list[GateRecord]:
        return [
            GateRecord(
                stable_id=f"gate:{gate.value}",
                name=definition["name"],
                source="photonic gate definitions",
                status=GateStatus.BLOCKED,
                validity="unknown",
                gate=gate,
                reason="required evidence has not been recorded",
                next_action=f"collect evidence for {gate.value}",
            )
            for gate, definition in GATE_DEFINITIONS.items()
        ]

    def load(self, *, create_if_missing: bool = False) -> list[GateRecord]:
        if not self.path.exists():
            records = self.default_records()
            if create_if_missing:
                self.save(records)
            return records
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"invalid gate ledger JSON: {self.path}: {exc}") from exc
        if not isinstance(payload, list):
            raise InvalidInputError("gate ledger must be a JSON array")
        records: list[GateRecord] = []
        for item in payload:
            model = parse_contract(item, "GateRecord")
            assert isinstance(model, GateRecord)
            records.append(model)
        actual = {record.gate for record in records}
        missing = set(GATE_DEFINITIONS) - actual
        duplicates = len(actual) != len(records)
        if missing or duplicates:
            raise InvalidInputError(
                "gate ledger must contain each G0-G8 and M0-M4 exactly once"
            )
        return records

    def save(self, records: list[GateRecord]) -> None:
        payload = [contract_payload(record) for record in records]
        atomic_write_text(
            self.path,
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validated_evidence_file(self, raw_path: str) -> tuple[Path, str]:
        cleaned = raw_path.strip()
        if not cleaned:
            raise InvalidInputError("gate evidence path must not be empty")
        relative = Path(cleaned)
        if relative.is_absolute():
            raise InvalidInputError("gate evidence must use a project-relative path")
        candidate = (self.project_root / relative).resolve()
        try:
            normalized = candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise InvalidInputError("gate evidence escaped the project root") from exc
        if candidate == self.path.resolve():
            raise InvalidInputError(
                "the live gate ledger cannot serve as its own hashed evidence; "
                "use an immutable project-relative snapshot"
            )
        if not candidate.is_file():
            raise InvalidInputError(f"gate evidence is not a readable file: {normalized.as_posix()}")
        if candidate.stat().st_size <= 0:
            raise InvalidInputError(f"gate evidence file is empty: {normalized.as_posix()}")
        try:
            with candidate.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            raise InvalidInputError(
                f"gate evidence is not readable: {normalized.as_posix()}"
            ) from exc
        return candidate, normalized.as_posix()

    def _canonicalize_accepted_evidence(
        self,
        gate: GateName,
        status: GateStatus,
        evidence: list[str],
        *,
        digest_cache: dict[Path, str] | None = None,
    ) -> list[str]:
        definition = GATE_DEFINITIONS[gate]
        if status == GateStatus.NOT_APPLICABLE:
            if not definition["allows_not_applicable"]:
                raise InvalidInputError(f"{gate.value} cannot be marked not_applicable")
            expected = {"applicability"}
        else:
            expected = set(definition["requires"])
        if not evidence:
            raise InvalidInputError("an accepted gate requires mapped evidence")

        mapped: dict[str, str] = {}
        canonical: list[str] = []
        cache = digest_cache if digest_cache is not None else {}
        for item in evidence:
            if "=" not in item:
                raise InvalidInputError(
                    "accepted gate evidence must use CHECK=PROJECT_RELATIVE_PATH"
                )
            check, raw_value = item.split("=", 1)
            check = check.strip()
            if check not in expected:
                raise InvalidInputError(
                    f"unknown evidence check for {gate.value}: {check or '<empty>'}"
                )
            if check in mapped:
                raise InvalidInputError(f"duplicate evidence check for {gate.value}: {check}")

            supplied_digest: str | None = None
            raw_path = raw_value
            if raw_value.startswith(_DIGEST_PREFIX):
                digest_and_path = raw_value.removeprefix(_DIGEST_PREFIX).split(":", 1)
                if len(digest_and_path) != 2:
                    raise InvalidInputError(f"invalid evidence digest syntax for {check}")
                supplied_digest, raw_path = digest_and_path
                if len(supplied_digest) != 64 or any(
                    character not in "0123456789abcdefABCDEF" for character in supplied_digest
                ):
                    raise InvalidInputError(f"invalid SHA-256 digest for {check}")

            path, relative = self._validated_evidence_file(raw_path)
            actual_digest = cache.get(path)
            if actual_digest is None:
                actual_digest = self._sha256(path)
                cache[path] = actual_digest
            if supplied_digest is not None and supplied_digest.lower() != actual_digest:
                raise InvalidInputError(f"gate evidence digest changed for {check}: {relative}")
            mapped[check] = relative
            canonical.append(f"{check}={_DIGEST_PREFIX}{actual_digest}:{relative}")

        missing = sorted(expected - set(mapped))
        if missing:
            raise InvalidInputError(
                f"missing evidence checks for {gate.value}: {', '.join(missing)}"
            )
        return canonical

    def _evaluate_record(
        self,
        record: GateRecord,
        *,
        digest_cache: dict[Path, str],
    ) -> dict[str, Any]:
        if record.status not in _ACCEPTED_GATE_STATUSES:
            return {
                "effective_status": record.status.value,
                "evidence_policy": "not-accepted",
                "evidence_references_resolved": False,
                "evidence_issues": [],
            }
        if not record.evidence or all("=" not in item for item in record.evidence):
            return {
                "effective_status": "unverified",
                "evidence_policy": "legacy-unverified",
                "evidence_references_resolved": False,
                "evidence_issues": [
                    "legacy accepted record has no per-requirement mapping or recorded digest"
                ],
            }
        if record.evidence and any("=" not in item for item in record.evidence):
            return {
                "effective_status": GateStatus.BLOCKED.value,
                "evidence_policy": "mapped-invalid",
                "evidence_references_resolved": False,
                "evidence_issues": ["legacy and mapped evidence cannot be mixed"],
            }
        try:
            self._canonicalize_accepted_evidence(
                record.gate,
                record.status,
                record.evidence,
                digest_cache=digest_cache,
            )
        except InvalidInputError as exc:
            return {
                "effective_status": GateStatus.BLOCKED.value,
                "evidence_policy": "mapped-invalid",
                "evidence_references_resolved": False,
                "evidence_issues": [str(exc)],
            }
        return {
            "effective_status": record.status.value,
            "evidence_policy": "mapped-sha256",
            "evidence_references_resolved": True,
            "evidence_issues": [],
        }

    def update(
        self,
        gate: GateName,
        status: GateStatus,
        *,
        evidence: list[str],
        metrics: dict[str, float | str] | None = None,
        reason: str,
        next_action: str,
        dry_run: bool = False,
    ) -> GateRecord:
        if status == GateStatus.NOT_APPLICABLE and not reason.strip():
            raise InvalidInputError("not_applicable requires a reason")
        checked_evidence = evidence
        if status in _ACCEPTED_GATE_STATUSES:
            checked_evidence = self._canonicalize_accepted_evidence(gate, status, evidence)
        records = self.load(create_if_missing=not dry_run)
        index = next((index for index, record in enumerate(records) if record.gate == gate), None)
        if index is None:
            raise InvalidInputError(f"unknown gate: {gate.value}")
        previous = records[index]
        payload = previous.model_dump()
        payload.update(
            {
                "revision": str(int(previous.revision) + 1) if previous.revision.isdigit() else previous.revision,
                "status": status,
                "validity": Validity.VALID if status == GateStatus.PASS else Validity.UNKNOWN,
                "evidence": checked_evidence,
                "metrics": metrics or {},
                "reason": reason,
                "next_action": next_action,
            }
        )
        updated = revalidate_internal(GateRecord, payload)
        records[index] = updated
        if not dry_run:
            self.save(records)
        return updated

    def summary(self) -> dict[str, Any]:
        records = self.load()
        digest_cache: dict[Path, str] = {}
        evaluations = {
            record.gate: self._evaluate_record(record, digest_cache=digest_cache)
            for record in records
        }
        profiles: dict[str, Any] = {}
        for profile, gates in GATE_PROFILES.items():
            required_pass = _PROFILE_REQUIRED_PASS[profile]
            effective = {
                gate.value: evaluations[gate]["effective_status"]
                for gate in gates
            }
            profiles[profile] = {
                "kind": "overlay" if profile in _OVERLAY_PROFILES else "base",
                "required_gates": [gate.value for gate in gates],
                "required_pass_gates": [
                    gate.value for gate in gates if gate in required_pass
                ],
                "conditionally_applicable_gates": [
                    gate.value for gate in gates if gate not in required_pass
                ],
                "effective_statuses": effective,
                "all_required_gates_evidence_verified": all(
                    effective[gate.value] == GateStatus.PASS.value
                    if gate in required_pass
                    else effective[gate.value]
                    in {GateStatus.PASS.value, GateStatus.NOT_APPLICABLE.value}
                    for gate in gates
                ),
            }
        return {
            "initialized": self.path.is_file(),
            "gates": [
                {
                    "gate": record.gate.value,
                    "name": record.name,
                    "status": record.status.value,
                    **evaluations[record.gate],
                    "evidence_count": len(record.evidence),
                    "requirements": list(GATE_DEFINITIONS[record.gate]["requires"]),
                    "applies_when": GATE_DEFINITIONS[record.gate]["applies_when"],
                    "allows_not_applicable": GATE_DEFINITIONS[record.gate]["allows_not_applicable"],
                    "reason": record.reason,
                    "next_action": record.next_action,
                }
                for record in records
            ],
            "all_gates_passed": all(
                record.status in {GateStatus.PASS, GateStatus.NOT_APPLICABLE}
                for record in records
                if record.gate.value.startswith("G")
            ),
            "measurement_track_complete": all(
                record.status in {GateStatus.PASS, GateStatus.NOT_APPLICABLE}
                for record in records
                if record.gate.value.startswith("M")
            ),
            "all_gates_evidence_verified": all(
                evaluations[GateName(f"G{index}")]["effective_status"]
                == GateStatus.PASS.value
                for index in range(9)
            ),
            "measurement_track_evidence_verified": profiles["recalibration"][
                "all_required_gates_evidence_verified"
            ],
            "closure_profiles": profiles,
            "ledger_semantics": {
                "advisory_requires_ledger": False,
                "recorded_status_is_preserved": True,
                "strict_evidence_syntax": "CHECK=PROJECT_RELATIVE_PATH",
                "strict_evidence_proves": "requirement references resolve to nonempty hashed files",
                "strict_evidence_does_not_prove": "scientific correctness or physical acceptance",
            },
        }
