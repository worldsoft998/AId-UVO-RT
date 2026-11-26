import os

from aiduvo.lint import check_files, check_repo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_framework_is_compliant():
    report = check_repo(ROOT)
    assert report.ok, report.render()
    assert report.checked_files > 20


def test_hdl_files_are_only_in_user_space():
    report = check_repo(ROOT)
    for path in report.hdl_files_found:
        assert path.startswith(("examples/", "scripts/")), path


def test_check_files_flags_forbidden_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import pyverilog\n")
    report = check_files([str(bad)])
    assert not report.ok
    assert any(v.rule == "R2" for v in report.violations)
