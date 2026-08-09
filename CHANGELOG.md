# Changelog

All notable changes are recorded here. Versions follow Semantic Versioning;
recipe schema and recipe semantic versions are maintained independently from
the host package version.

## [Unreleased]

### Changed

- Split skill-internal gate use into lightweight advisory mode and claim-scoped
  evidence mode, with composable base profiles and promotion/delivery overlays.
- Replaced label-only gate evidence with project-relative, SHA-256-bound
  `CHECK=PATH` evidence mappings for new PASS/N/A transitions; legacy records
  remain readable but are reported as unverified rather than silently promoted.
- Made passivity, reciprocity, unitarity, power closure, causality, convergence,
  field review, and manufacturability checks conditional on the device physics
  and the claim being promoted instead of universal entry requirements.
- Documented COMSOL study-sequence, convergence, and export contracts without
  claiming unverified renderer coverage, and clarified the current native-adjoint
  boundary, evidence cadence, checkpointing, and concurrency expectations.
- Repositioned the skill as a solver-agnostic, auditable photonic design and
  closure workflow while retaining COMSOL as a bounded adapter and historical
  repository name.
- Tightened numeric-port and open-boundary selection guidance with an exact,
  fail-closed exterior partition audit derived from corrected SOI splitter
  modeling experience and reconciled with COMSOL's local cross-section model.
- Added mandatory physical field-image review rules so implausible confinement,
  launch area, leakage, PML concentration, or plot context blocks acceptance.
- Switched the trusted Windows Java compile route to COMSOL's official
  `comsolcompile` entrypoint before `comsolbatch`, retaining the legacy wrapper
  parameter alias for compatibility and safely normalizing COMSOL's unique
  named-model output suffix.

Implementation and validation: OpenAI Codex.

## [0.4.0] - 2026-08-01

### Added

- Installable `photonic-workflow` package, `photonic` CLI, bounded MCP server,
  adapter SPI, project/run stores, versioned contracts, adoption gates, and
  solver-independent workflow profiles.
- Six deterministic modeling recipes distilled by reviewed behavioral and
  public-formula reimplementation from two read-only LT-aMZI projects: circular and
  symmetric-Euler geometry, segmented port windows, Li silicon and Malitson
  fused-silica bulk dispersion, and common-basis two-port diagnostics.
- Strict recipe request schemas, exact recipe versions, parameter contracts,
  packaged provenance hashes, canonical JSON output, and allowlisted fixed
  numeric COMSOL Java fragments for geometry/port setup only.
- MATLAB Phase A contracts and probes, external-backend adoption ledgers,
  package resource mirrors, artifact audits, and multi-context GitHub Actions
  validation.
- Python 3.11-3.14 compatibility lanes, checked-in skill/UI metadata schema
  validation, SHA-pinned Actions, split release permissions, SHA-256 release
  inventories, and GitHub build-provenance attestations.

### Changed

- Legacy Python and PowerShell entry points now delegate to package services
  while retaining regression-tested compatibility contracts.
- The legacy analytic-bend helper no longer writes arbitrary `--output` paths;
  bounded fragment creation is provided by `photonic recipe render`.
- MCP resource counts are derived from one registry and verified against source,
  packaged, and installed-wheel resources instead of duplicated magic numbers.
- The minimal third-party adapter example now declares host compatibility
  `photonic-workflow>=0.4,<0.5`.

### Evidence boundaries

- Recipe evaluation and rendering do not execute COMSOL or establish full-wave
  validation, convergence, fabrication readiness, or device acceptance.
- MATLAB Phase B remains blocked by the recorded native startup crash in the
  required normal interactive Windows context. LiveLink, Lumerical, instruments,
  and real PDK/DRC/LVS integrations remain separate Phase C adoption gates.

[Unreleased]: https://github.com/Bian-M-X/comsol-photonic-waveguide-optics-skill/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Bian-M-X/comsol-photonic-waveguide-optics-skill/releases/tag/v0.4.0
