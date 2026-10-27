"""Tests for project detection (patchproof.detect)."""

from __future__ import annotations

import json

from patchproof.detect import _probe, _probe_module, detect_project


def test_python_detection_with_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n", encoding="utf-8"
    )
    facts = detect_project(str(tmp_path))
    assert facts.languages == ["python"]
    purposes = {hint.purpose for hint in facts.hints}
    assert "test" in purposes
    assert "lint" in purposes
    test_hint = facts.hints_for("test")[0]
    assert test_hint.command == ["python", "-m", "pytest", "-q"]
    assert "pyproject.toml" in test_hint.basis


def test_javascript_detection_with_frameworks(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"test": "jest"},
                "dependencies": {"react": "^18.0.0"},
                "devDependencies": {
                    "jest": "^29.0.0",
                    "eslint": "^8.0.0",
                    "typescript": "^5.0.0",
                },
            }
        ),
        encoding="utf-8",
    )
    facts = detect_project(str(tmp_path))
    assert "javascript" in facts.languages
    assert "react" in facts.frameworks
    commands = [hint.command for hint in facts.hints]
    assert ["npm", "run", "test"] in commands
    assert ["npx", "eslint", "."] in commands
    assert ["npx", "tsc", "--noEmit"] in commands


def test_typescript_config_detected(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    facts = detect_project(str(tmp_path))
    assert facts.languages == ["typescript"]


def test_empty_tree_warns_about_missing_language_configs(tmp_path):
    facts = detect_project(str(tmp_path))
    assert facts.languages == []
    assert any("no language configuration" in warning for warning in facts.warnings)


def test_malformed_package_json_warns_and_still_detects_javascript(tmp_path):
    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
    facts = detect_project(str(tmp_path))
    assert "javascript" in facts.languages
    assert any("not valid JSON" in warning for warning in facts.warnings)


def test_hints_for_filters_by_purpose(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n", encoding="utf-8"
    )
    facts = detect_project(str(tmp_path))
    assert len(facts.hints_for("test")) == 1
    assert len(facts.hints_for("lint")) == 1
    assert len(facts.hints_for("typecheck")) == 1
    assert facts.hints_for("deps") == []


def test_missing_executable_probes_honestly():
    available, version = _probe("definitely-not-a-real-tool-xyz")
    assert available is False
    assert version is None


def test_missing_module_probes_honestly():
    available, version = _probe_module("python", "definitely_not_a_module_xyz")
    assert available is False
    assert version is None


def test_facts_root_is_absolute(tmp_path):
    facts = detect_project(str(tmp_path))
    assert facts.root.endswith(str(tmp_path.name))
