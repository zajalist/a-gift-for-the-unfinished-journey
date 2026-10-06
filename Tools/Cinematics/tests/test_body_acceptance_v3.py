import ast
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_body_acceptance_v3 as prepare


class BindingID:
    def __init__(self,text):self.text=text
    def export_text(self):return self.text


def test_binding_value_comparison_accepts_distinct_wrappers_and_rejects_changed_fields():
    code='def same_binding(actual_id, binding):\n    expected_id = seq.get_binding_id(binding)\n'+prepare.NEW+'\n'
    expected='(Guid=ABC,SequenceID=0,ResolveParentIndex=0)'
    context={'seq':SimpleNamespace(get_binding_id=lambda _:BindingID(expected))}
    exec(compile(ast.parse(code),'<value-check>','exec'),context)
    compare=context['same_binding']
    assert compare(BindingID(expected),object())
    for changed in ('(Guid=DEF,SequenceID=0,ResolveParentIndex=0)',
                    '(Guid=ABC,SequenceID=1,ResolveParentIndex=0)',
                    '(Guid=ABC,SequenceID=0,ResolveParentIndex=1)'):
        assert not compare(BindingID(changed),object())
