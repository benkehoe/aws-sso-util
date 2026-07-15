import collections
import datetime

import pytest

from aws_sso_util.visualize import (
    assignment_to_row,
    render_access_graph,
    write_access_graph,
)

# Mirrors aws_sso_lib.assignments.Assignment; the renderer only relies on
# attribute access, so the test does not need aws_sso_lib installed.
Assignment = collections.namedtuple("Assignment", [
    "instance_arn",
    "principal_type",
    "principal_id",
    "principal_name",
    "permission_set_arn",
    "permission_set_name",
    "target_type",
    "target_id",
    "target_name",
])


def make_assignment(**kwargs):
    values = dict(
        instance_arn="arn:aws:sso:::instance/ssoins-0123456789abcdef",
        principal_type="GROUP",
        principal_id="01234567-89ab-cdef-0123-456789abcdef",
        principal_name="Platform Engineering",
        permission_set_arn="arn:aws:sso:::permissionSet/ssoins-0123456789abcdef/ps-0123456789abcdef",
        permission_set_name="AWSReadOnlyAccess",
        target_type="AWS_ACCOUNT",
        target_id="123456789012",
        target_name="workloads-dev",
    )
    values.update(kwargs)
    return Assignment(**values)


def test_assignment_to_row_uses_names():
    row = assignment_to_row(make_assignment())
    assert row == [
        "GROUP",
        "Platform Engineering",
        "AWSReadOnlyAccess",
        "123456789012",
        "workloads-dev",
    ]


def test_assignment_to_row_falls_back_to_identifiers():
    a = make_assignment(principal_name=None, permission_set_name=None, target_name=None)
    row = assignment_to_row(a)
    assert row[1] == a.principal_id
    assert row[2] == a.permission_set_arn
    assert row[4] == a.target_id


def test_render_injects_data_and_date():
    html = render_access_graph([make_assignment()], generated_at="2026-01-02")
    assert "/*DATA*/" not in html
    assert "/*DATE*/" not in html
    assert "Platform Engineering" in html
    assert "2026-01-02" in html


def test_render_defaults_date_to_today():
    html = render_access_graph([])
    assert datetime.date.today().isoformat() in html


def test_render_empty_assignments():
    html = render_access_graph([], generated_at="2026-01-02")
    assert "const DATA = [];" in html


def test_render_escapes_script_breakout():
    a = make_assignment(principal_name='</script><script>alert(1)</script>')
    html = render_access_graph([a], generated_at="2026-01-02")
    # the template legitimately contains its own closing tag exactly once
    assert html.count("</script>") == 1
    assert "\\u003c/script>" in html


def test_render_is_self_contained():
    html = render_access_graph([make_assignment()], generated_at="2026-01-02")
    # no external scripts, stylesheets, imports, or network calls
    for marker in ("<script src", "<link ", "@import", "fetch(", "XMLHttpRequest", "https://"):
        assert marker not in html, marker


def test_write_access_graph(tmp_path):
    out = tmp_path / "graph.html"
    count = write_access_graph([make_assignment(), make_assignment(target_id="210987654321", target_name="workloads-prod")], str(out))
    assert count == 2
    content = out.read_text(encoding="utf-8")
    assert "workloads-prod" in content


def test_render_rejects_missing_placeholder(monkeypatch):
    import aws_sso_util.visualize as v
    monkeypatch.setattr(v, "_DATA_PLACEHOLDER", "not in the template")
    with pytest.raises(RuntimeError):
        render_access_graph([])
