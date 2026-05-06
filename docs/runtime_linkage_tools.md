# Runtime Linkage Tools

E51 exposes Y-star-gov runtime-linkage validators through gov-mcp without starting external services or mutating client configuration.

Tools:

- `gov_validate_runtime_linkage(payload)` validates a runtime linkage graph.
- `gov_validate_centerline_contract(payload)` validates the centerline contract.
- `gov_validate_readback_proof(payload)` validates writer/readback observations.
- `gov_enforce_anti_drift_gate(payload)` evaluates the full anti-drift gate and returns ALLOW or DENY.

Each tool accepts a JSON string or dictionary payload and returns a deterministic JSON envelope with `status`, `allowed`, `failures`, `warnings`, artifact counts, P0/P1 failure counts, and `no_external_action: true`.

These tools do not perform outreach, publication, login, package installation, payment, secret access, or real client configuration mutation.

## Capability Centerline Binding Tools

- `gov_validate_capability_binding`: validates one capability binding record.
- `gov_enforce_capability_centerline_gate`: enforces the capability-centerline binding gate for a manifest.

These tools deny P0 cognitive capabilities outside CEO brain, behavior controls outside canonical runtime/governance, current-state evidence without readback, and reference-only artifacts consumed as current state. No external action is performed.
