import json

from gov_mcp.runtime_linkage_tools import register_runtime_linkage_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def contract():
    return {
        'contract_id': 'capability_centerline_contract',
        'class_rules': {
            'cognitive_capability': {'required_centerline': ['CEO_brain']},
            'behavior_control_capability': {'required_centerline': ['canonical_action_runtime', 'Y_star_gov_boundary']},
            'evidence_closure_capability': {'required_centerline': ['KG_CZL_CIEU_K9_evidence']},
            'boundary_capability': {'required_centerline': ['Y_star_gov_boundary']},
            'reference_only_artifact': {'required_centerline': ['reference_only']},
        },
        'no_external_action': True,
    }


def record(capability_id, functional_class, actual_binding, *, status='correctly_bound', severity='P0', consumed_as_current=False):
    required = {
        'cognitive_capability': ['CEO_brain'],
        'behavior_control_capability': ['canonical_action_runtime', 'Y_star_gov_boundary'],
        'evidence_closure_capability': ['KG_CZL_CIEU_K9_evidence'],
        'boundary_capability': ['Y_star_gov_boundary', 'gov_mcp_boundary'],
        'reference_only_artifact': ['reference_only'],
    }[functional_class]
    return {
        'capability_id': capability_id,
        'path': f'{capability_id}.json',
        'repo': 'bridge-labs',
        'functional_class': functional_class,
        'required_centerline': required,
        'actual_binding': actual_binding,
        'binding_status': status,
        'required_reader': 'reader' if functional_class != 'reference_only_artifact' else '',
        'actual_reader': 'reader' if functional_class != 'reference_only_artifact' else '',
        'required_gate': 'gate' if functional_class in {'behavior_control_capability', 'boundary_capability'} else '',
        'actual_gate': 'gate' if functional_class in {'behavior_control_capability', 'boundary_capability'} else '',
        'remediation': 'no_action',
        'severity': severity,
        'consumed_as_current': consumed_as_current,
        'agent_facing': functional_class == 'boundary_capability',
        'affects_current_state': functional_class == 'evidence_closure_capability',
        'evidence_basis': 'test',
    }


def valid_payload():
    return {
        'gate_id': 'valid_capability_gate',
        'capability_centerline_contract': contract(),
        'capability_bindings': [
            record('semantic_runtime', 'cognitive_capability', ['CEO_brain']),
            record('demo_runner', 'behavior_control_capability', ['canonical_action_runtime', 'Y_star_gov_boundary']),
            record('czl', 'evidence_closure_capability', ['KG_CZL_CIEU_K9_evidence']),
            record('boundary', 'boundary_capability', ['Y_star_gov_boundary', 'gov_mcp_boundary']),
            record('old_report', 'reference_only_artifact', ['reference_only'], status='reference_only_ok', severity='P3'),
        ],
    }


def test_capability_binding_tools_register():
    fake = FakeMCP()
    register_runtime_linkage_tools(fake)
    assert {'gov_validate_capability_binding', 'gov_enforce_capability_centerline_gate'}.issubset(fake.tools)


def test_capability_centerline_gate_allows_valid_payload():
    fake = FakeMCP()
    register_runtime_linkage_tools(fake)
    result = json.loads(fake.tools['gov_enforce_capability_centerline_gate'](json.dumps(valid_payload())))
    assert result['status'] == 'ALLOW'
    assert result['allowed'] is True
    assert result['no_external_action'] is True


def test_capability_centerline_gate_denies_cognitive_missing_brain_binding():
    fake = FakeMCP()
    register_runtime_linkage_tools(fake)
    payload = valid_payload()
    payload['capability_bindings'][0]['actual_binding'] = ['reference_only']
    payload['capability_bindings'][0]['binding_status'] = 'missing_binding'
    payload['capability_bindings'][0]['actual_reader'] = ''
    result = json.loads(fake.tools['gov_enforce_capability_centerline_gate'](payload))
    assert result['status'] == 'DENY'
    assert result['p0_failure_count'] >= 1


def test_capability_centerline_gate_denies_behavior_bypass_and_reference_current():
    fake = FakeMCP()
    register_runtime_linkage_tools(fake)
    payload = valid_payload()
    payload['capability_bindings'][1]['actual_binding'] = ['Y_star_gov_boundary']
    payload['capability_bindings'][1]['binding_status'] = 'wrong_centerline'
    payload['capability_bindings'][4]['consumed_as_current'] = True
    result = json.loads(fake.tools['gov_enforce_capability_centerline_gate'](json.dumps(payload)))
    assert result['status'] == 'DENY'
    assert result['allowed'] is False
