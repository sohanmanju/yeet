"""Project recognition policies retain their distinct ownership requirements."""

from yeet.models import ProjectType
from yeet.project_rules import contains_project_marker, detect_project_type


def test_git_requirements_and_marker_precedence():
    assert detect_project_type({"requirements.txt"}) is None
    assert detect_project_type({".git", "requirements.txt"}) is ProjectType.PYTHON
    assert (
        detect_project_type({".git", "requirements.txt", "package.json"})
        is ProjectType.NODE
    )
    assert detect_project_type({".git", "Gemfile"}) is ProjectType.GIT
    assert detect_project_type({"Gemfile"}) is ProjectType.OTHER


def test_artifact_ownership_recognizes_additional_project_formats():
    for marker in ("Pipfile", "Package.swift", "Example.csproj", "build.gradle.kts"):
        assert contains_project_marker({marker})
        assert detect_project_type({marker}) is None
