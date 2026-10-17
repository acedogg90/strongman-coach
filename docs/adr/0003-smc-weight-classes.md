# ADR-0003: SMC Weight Classes

## Status
Accepted

## Context
Strongman competitions use bodyweight classes. The Strongman Corporation (SMC) defines specific kg classes for amateur and masters divisions.

## Decision
The app uses SMC weight classes:
- **Amateur**: 80 / 90 / 105 / 120 kg / Heavyweight (over 120 kg)
- **Masters 40+**: 80 / 90 / 105 kg / Heavyweight (over 105 kg)

The appropriate class set is selected based on the athlete's age (≥ 40 → Masters).

## Consequences
- Benchmark targets are tied to the athlete's current class.
- If the athlete's age crosses 40, the class set changes automatically.
- Benchmarks are seeded from ASM 2025 values per class.
