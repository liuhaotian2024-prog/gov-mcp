from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _ensure_ystar_governance_path() -> None:
    root = Path(os.environ.get('YSTAR_GOV_ROOT', '/Users/haotianliu/.openclaw/workspace/Y-star-gov'))
    if root.exists() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _coerce_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            return {'__parse_error__': str(exc), '__raw__': payload}
    if isinstance(payload, dict):
        return payload
    return {'__unsupported_payload_type__': type(payload).__name__}


def _envelope(tool_name: str, result: dict[str, Any], *, allowed: bool | None = None) -> str:
    failures = result.get('failures') or []
    p0 = result.get('p0_failure_count')
    p1 = result.get('p1_failure_count')
    if p0 is None:
        p0 = sum(1 for item in failures if item.get('severity') == 'P0')
    if p1 is None:
        p1 = sum(1 for item in failures if item.get('severity') == 'P1')
    if allowed is None:
        allowed = bool(result.get('valid', result.get('allowed', False)))
    envelope = {
        'tool_name': tool_name,
        'status': 'ALLOW' if allowed else 'DENY',
        'allowed': allowed,
        'failures': failures,
        'warnings': result.get('warnings', []),
        'validated_artifact_count': result.get('validated_artifact_count', result.get('artifact_count', 0)),
        'p0_failure_count': p0,
        'p1_failure_count': p1,
        'result': result,
        'no_external_action': True,
    }
    return json.dumps(envelope, indent=2, ensure_ascii=False)


def register_runtime_linkage_tools(mcp: Any, state: Any = None) -> None:
    _ensure_ystar_governance_path()
    from ystar.governance.anti_drift_gate import evaluate_anti_drift_gate
    from ystar.governance.centerline_contract import validate_centerline_contract
    from ystar.governance.readback_proof import validate_readback_proof
    from ystar.governance.runtime_linkage import validate_runtime_linkage_graph

    @mcp.tool()
    def gov_validate_runtime_linkage(payload: Any) -> str:
        data = _coerce_payload(payload)
        if '__parse_error__' in data or '__unsupported_payload_type__' in data:
            return _envelope('gov_validate_runtime_linkage', {'valid': False, 'failures': [{'reason': 'invalid_payload', 'details': data}]}, allowed=False)
        graph = data.get('runtime_linkage_graph') if isinstance(data.get('runtime_linkage_graph'), dict) else data
        result = validate_runtime_linkage_graph(graph)
        result['validated_artifact_count'] = len(data.get('artifacts', [])) if isinstance(data, dict) else 0
        return _envelope('gov_validate_runtime_linkage', result, allowed=result.get('valid') is True)

    @mcp.tool()
    def gov_validate_centerline_contract(payload: Any) -> str:
        data = _coerce_payload(payload)
        if '__parse_error__' in data or '__unsupported_payload_type__' in data:
            return _envelope('gov_validate_centerline_contract', {'valid': False, 'failures': [{'reason': 'invalid_payload', 'details': data}]}, allowed=False)
        contract = data.get('centerline_contract') if isinstance(data.get('centerline_contract'), dict) else data
        result = validate_centerline_contract(contract)
        return _envelope('gov_validate_centerline_contract', result, allowed=result.get('valid') is True)

    @mcp.tool()
    def gov_validate_readback_proof(payload: Any) -> str:
        data = _coerce_payload(payload)
        if '__parse_error__' in data or '__unsupported_payload_type__' in data:
            return _envelope('gov_validate_readback_proof', {'valid': False, 'failures': [{'reason': 'invalid_payload', 'details': data}]}, allowed=False)
        proof = data.get('readback_proof') if isinstance(data.get('readback_proof'), dict) else data
        result = validate_readback_proof(proof)
        return _envelope('gov_validate_readback_proof', result, allowed=result.get('valid') is True)

    @mcp.tool()
    def gov_enforce_anti_drift_gate(payload: Any) -> str:
        data = _coerce_payload(payload)
        if '__parse_error__' in data or '__unsupported_payload_type__' in data:
            return _envelope('gov_enforce_anti_drift_gate', {'allowed': False, 'failures': [{'reason': 'invalid_payload', 'details': data}], 'status': 'anti_drift_gate_failed_unknown'}, allowed=False)
        result = evaluate_anti_drift_gate(data)
        return _envelope('gov_enforce_anti_drift_gate', result, allowed=result.get('allowed') is True)
