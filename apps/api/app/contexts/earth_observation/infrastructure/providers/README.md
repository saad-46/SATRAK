# infrastructure/providers

Imagery **provider adapters** — the capability-driven extension mechanism (ADR-0007). Two families: `satellite/` (spaceborne) and `aerial/` (manned airborne). **Drone/UAV imagery is deliberately excluded** — it belongs to the `drone` bounded context (ADR-0010). Adding a provider touches only this tree.
