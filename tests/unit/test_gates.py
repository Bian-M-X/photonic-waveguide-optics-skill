from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.gates import GATE_DEFINITIONS, GATE_PROFILES, GateLedger
from photonic_workflow.models import GateName, GateStatus, Validity


def _artifact(root: Path, name: str = "verification/evidence.md") -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("reviewed evidence\n", encoding="utf-8")
    return path.relative_to(root).as_posix()


def _pass_evidence(gate: GateName, relative: str) -> list[str]:
    return [
        f"{requirement}={relative}"
        for requirement in GATE_DEFINITIONS[gate]["requires"]
    ]


class GateLedgerTests(unittest.TestCase):
    def test_profile_inventory_does_not_initialize_an_exploratory_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = GateLedger(Path(temporary))
            summary = ledger.summary()
            self.assertFalse(summary["initialized"])
            self.assertFalse(summary["ledger_semantics"]["exploratory_requires_ledger"])
            self.assertFalse(summary["ledger_semantics"]["profile_selection_is_persisted"])
            self.assertFalse(ledger.path.exists())

    def test_scoped_profiles_do_not_promote_broader_claims(self) -> None:
        cases = (
            ("layout-connectivity", (GateName.G0, GateName.G5), "layout-tapeout"),
            ("measurement-capture", (GateName.M0, GateName.M1), "measurement"),
        )
        for profile, gates, broader in cases:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                evidence = _artifact(root)
                ledger = GateLedger(root)
                for gate in gates:
                    ledger.update(
                        gate, GateStatus.PASS,
                        evidence=_pass_evidence(gate, evidence),
                        reason="scoped evidence reviewed", next_action="report scoped claim",
                    )
                profiles = ledger.summary()["closure_profiles"]
                self.assertTrue(profiles[profile]["all_required_gates_evidence_verified"])
                self.assertFalse(profiles[broader]["all_required_gates_evidence_verified"])
                self.assertEqual(profiles[profile]["conditionally_applicable_gates"], [])
                (root / evidence).write_text("changed evidence\n", encoding="utf-8")
                self.assertFalse(
                    ledger.summary()["closure_profiles"][profile][
                        "all_required_gates_evidence_verified"
                    ]
                )

    def test_layout_connectivity_cannot_close_with_g5_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = _artifact(root)
            ledger = GateLedger(root)
            ledger.update(
                GateName.G0, GateStatus.PASS, evidence=_pass_evidence(GateName.G0, evidence),
                reason="contract reviewed", next_action="check layout",
            )
            ledger.update(
                GateName.G5, GateStatus.NOT_APPLICABLE,
                evidence=[f"applicability={evidence}"],
                reason="no layout claim", next_action="do not select layout profile",
            )
            self.assertFalse(
                ledger.summary()["closure_profiles"]["layout-connectivity"][
                    "all_required_gates_evidence_verified"
                ]
            )

    def test_gate_definition_snapshot_covers_g_and_measurement_tracks(self) -> None:
        self.assertEqual(
            [gate.value for gate in GATE_DEFINITIONS],
            [f"G{index}" for index in range(9)] + [f"M{index}" for index in range(5)],
        )
        self.assertEqual(GATE_PROFILES["component"], (GateName.G0, GateName.G1, GateName.G2))
        self.assertEqual(GATE_PROFILES["delivery-overlay"], (GateName.G8,))
        self.assertEqual(GATE_PROFILES["recalibration"][-1], GateName.M4)

    def test_missing_or_legacy_evidence_cannot_create_a_new_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = GateLedger(Path(temporary))
            records = ledger.load(create_if_missing=True)
            self.assertTrue(all(record.status == GateStatus.BLOCKED for record in records))
            with self.assertRaisesRegex(InvalidInputError, "mapped evidence"):
                ledger.update(
                    GateName.G1,
                    GateStatus.PASS,
                    evidence=[],
                    reason="",
                    next_action="",
                )
            with self.assertRaisesRegex(InvalidInputError, "CHECK=PROJECT_RELATIVE_PATH"):
                ledger.update(
                    GateName.G1,
                    GateStatus.PASS,
                    evidence=["verification/legacy.md"],
                    reason="",
                    next_action="",
                )

    def test_complete_mapped_evidence_is_hashed_and_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root)
            ledger = GateLedger(root)
            updated = ledger.update(
                GateName.G0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G0, relative),
                reason="device contract reviewed",
                next_action="build the port baseline",
            )
            self.assertTrue(all("=sha256:" in item for item in updated.evidence))
            summary = ledger.summary()
            g0 = summary["gates"][0]
            self.assertEqual(g0["status"], "pass")
            self.assertEqual(g0["effective_status"], "pass")
            self.assertEqual(g0["evidence_policy"], "mapped-sha256")
            self.assertTrue(g0["evidence_references_resolved"])
            self.assertFalse(summary["closure_profiles"]["component"]["all_required_gates_evidence_verified"])

    def test_repeated_check_mappings_hash_each_artifact_once_per_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root)
            ledger = GateLedger(root)
            with patch.object(
                GateLedger,
                "_sha256",
                wraps=GateLedger._sha256,
            ) as sha256:
                ledger.update(
                    GateName.G0,
                    GateStatus.PASS,
                    evidence=_pass_evidence(GateName.G0, relative),
                    reason="device contract reviewed",
                    next_action="build baseline",
                )
                self.assertEqual(sha256.call_count, 1)
                sha256.reset_mock()
                ledger.summary()
                self.assertEqual(sha256.call_count, 1)

    def test_missing_duplicate_unknown_and_mixed_checks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root)
            ledger = GateLedger(root)
            complete = _pass_evidence(GateName.G0, relative)
            cases = {
                "missing": complete[:-1],
                "duplicate": [*complete, complete[0]],
                "unknown": [*complete, f"unexpected={relative}"],
                "mixed": [*complete[:-1], relative],
            }
            patterns = {
                "missing": "missing evidence checks",
                "duplicate": "duplicate evidence check",
                "unknown": "unknown evidence check",
                "mixed": "CHECK=PROJECT_RELATIVE_PATH",
            }
            for label, evidence in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(
                    InvalidInputError, patterns[label]
                ):
                    ledger.update(
                        GateName.G0,
                        GateStatus.PASS,
                        evidence=evidence,
                        reason="",
                        next_action="",
                    )

    def test_invalid_evidence_paths_fail_closed_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = _artifact(root)
            empty = root / "verification" / "empty.md"
            empty.write_text("", encoding="utf-8")
            directory = root / "verification" / "directory"
            directory.mkdir()
            outside = root.parent / f"{root.name}-outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            try:
                cases = {
                    "absolute": str((root / valid).resolve()),
                    "escape": f"../{outside.name}",
                    "missing": "verification/missing.md",
                    "directory": "verification/directory",
                    "empty": "verification/empty.md",
                }
                patterns = {
                    "absolute": "project-relative",
                    "escape": "escaped",
                    "missing": "not a readable file",
                    "directory": "not a readable file",
                    "empty": "is empty",
                }
                for label, bad_path in cases.items():
                    evidence = _pass_evidence(GateName.G0, valid)
                    evidence[0] = f"{GATE_DEFINITIONS[GateName.G0]['requires'][0]}={bad_path}"
                    ledger = GateLedger(root)
                    with self.subTest(label=label), self.assertRaisesRegex(
                        InvalidInputError, patterns[label]
                    ):
                        ledger.update(
                            GateName.G0,
                            GateStatus.PASS,
                            evidence=evidence,
                            reason="",
                            next_action="",
                            dry_run=True,
                        )
                    self.assertFalse(ledger.path.exists())
            finally:
                outside.unlink(missing_ok=True)

    def test_changed_evidence_blocks_effective_status_but_preserves_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root)
            ledger = GateLedger(root)
            ledger.update(
                GateName.G0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G0, relative),
                reason="device contract reviewed",
                next_action="build baseline",
            )
            (root / relative).write_text("changed evidence\n", encoding="utf-8")
            summary = ledger.summary()
            g0 = summary["gates"][0]
            self.assertEqual(g0["status"], "pass")
            self.assertEqual(g0["effective_status"], "blocked")
            self.assertIn("digest changed", g0["evidence_issues"][0])

    def test_legacy_pass_remains_readable_but_is_not_strictly_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = GateLedger(root)
            records = ledger.load(create_if_missing=True)
            records[0] = records[0].model_copy(
                update={
                    "status": GateStatus.PASS,
                    "validity": Validity.VALID,
                    "evidence": ["verification/legacy.md"],
                }
            )
            ledger.save(records)
            summary = ledger.summary()
            g0 = summary["gates"][0]
            self.assertEqual(g0["status"], "pass")
            self.assertEqual(g0["effective_status"], "unverified")
            self.assertEqual(g0["evidence_policy"], "legacy-unverified")
            self.assertFalse(summary["all_gates_evidence_verified"])

    def test_legacy_empty_not_applicable_remains_unverified_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = GateLedger(root)
            records = ledger.load(create_if_missing=True)
            records[3] = records[3].model_copy(
                update={
                    "status": GateStatus.NOT_APPLICABLE,
                    "validity": Validity.UNKNOWN,
                    "evidence": [],
                    "reason": "legacy record predates applicability evidence",
                }
            )
            ledger.save(records)
            g3 = next(item for item in ledger.summary()["gates"] if item["gate"] == "G3")
            self.assertEqual(g3["status"], "not_applicable")
            self.assertEqual(g3["effective_status"], "unverified")
            self.assertEqual(g3["evidence_policy"], "legacy-unverified")

    def test_conditional_not_applicable_requires_hashed_scope_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root, "requirements/scope.md")
            ledger = GateLedger(root)
            with self.assertRaisesRegex(InvalidInputError, "G0 cannot"):
                ledger.update(
                    GateName.G0,
                    GateStatus.NOT_APPLICABLE,
                    evidence=[f"applicability={relative}"],
                    reason="attempted bypass",
                    next_action="",
                )
            updated = ledger.update(
                GateName.G3,
                GateStatus.NOT_APPLICABLE,
                evidence=[f"applicability={relative}"],
                reason="no circuit composition is claimed",
                next_action="leave G3 outside the active claim profile",
            )
            self.assertIn("applicability=sha256:", updated.evidence[0])
            g3 = next(item for item in ledger.summary()["gates"] if item["gate"] == "G3")
            self.assertEqual(g3["effective_status"], "not_applicable")

    def test_profile_defining_gate_must_pass_and_overlay_is_composable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = _artifact(root)
            applicability = _artifact(root, "requirements/applicability.md")
            ledger = GateLedger(root)
            ledger.update(
                GateName.G0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G0, evidence),
                reason="contract reviewed",
                next_action="qualify component",
            )
            ledger.update(
                GateName.G1,
                GateStatus.NOT_APPLICABLE,
                evidence=[f"applicability={applicability}"],
                reason="no solver-derived port claim",
                next_action="retain analytic scope",
            )
            ledger.update(
                GateName.G2,
                GateStatus.NOT_APPLICABLE,
                evidence=[f"applicability={applicability}"],
                reason="no component qualification claimed",
                next_action="do not select component profile",
            )
            component = ledger.summary()["closure_profiles"]["component"]
            self.assertFalse(component["all_required_gates_evidence_verified"])
            self.assertEqual(component["required_pass_gates"], ["G0", "G2"])

            ledger.update(
                GateName.G2,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G2, evidence),
                reason="component evidence reviewed",
                next_action="compose or deliver",
            )
            summary = ledger.summary()
            self.assertTrue(
                summary["closure_profiles"]["component"][
                    "all_required_gates_evidence_verified"
                ]
            )
            delivery = summary["closure_profiles"]["delivery-overlay"]
            self.assertEqual(delivery["kind"], "overlay")
            self.assertFalse(delivery["all_required_gates_evidence_verified"])

    def test_delivery_overlay_cannot_make_all_gates_verified_without_a_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = _artifact(root)
            applicability = _artifact(root, "requirements/applicability.md")
            ledger = GateLedger(root)
            ledger.update(
                GateName.G0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G0, evidence),
                reason="contract reviewed",
                next_action="select a base profile",
            )
            for index in range(1, 8):
                gate = GateName(f"G{index}")
                ledger.update(
                    gate,
                    GateStatus.NOT_APPLICABLE,
                    evidence=[f"applicability={applicability}"],
                    reason="test fixture leaves the base profile incomplete",
                    next_action="do not infer base qualification",
                )
            ledger.update(
                GateName.G8,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G8, evidence),
                reason="delivery overlay evidence resolved",
                next_action="complete a defining base gate",
            )
            summary = ledger.summary()
            self.assertTrue(
                summary["closure_profiles"]["delivery-overlay"][
                    "all_required_gates_evidence_verified"
                ]
            )
            self.assertFalse(
                summary["closure_profiles"]["component"][
                    "all_required_gates_evidence_verified"
                ]
            )
            self.assertFalse(summary["all_gates_evidence_verified"])

    def test_live_gate_ledger_cannot_be_its_own_hashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = GateLedger(root)
            ledger.load(create_if_missing=True)
            with self.assertRaisesRegex(InvalidInputError, "cannot serve as its own"):
                ledger.update(
                    GateName.G0,
                    GateStatus.PASS,
                    evidence=_pass_evidence(GateName.G0, "verification/gates.json"),
                    reason="invalid circular evidence",
                    next_action="export an immutable snapshot",
                )

    def test_dry_run_is_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root)
            ledger = GateLedger(root)
            updated = ledger.update(
                GateName.G0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.G0, relative),
                reason="device contract reviewed",
                next_action="build baseline",
                dry_run=True,
            )
            self.assertEqual(updated.status, GateStatus.PASS)
            self.assertFalse(ledger.path.exists())

    def test_g_and_m_tracks_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = _artifact(root, "testplans/fixture.json")
            ledger = GateLedger(root)
            updated = ledger.update(
                GateName.M0,
                GateStatus.PASS,
                evidence=_pass_evidence(GateName.M0, relative),
                reason="test plan recorded",
                next_action="capture raw data",
            )
            self.assertEqual(updated.gate, GateName.M0)
            summary = ledger.summary()
            self.assertFalse(summary["all_gates_passed"])
            self.assertFalse(summary["measurement_track_complete"])
            self.assertFalse(summary["measurement_track_evidence_verified"])


if __name__ == "__main__":
    unittest.main()
