"""Tests for the migration_contiguity check."""

from specledger.checks import MIGRATION_CONTIGUITY, check_migration_contiguity


def details(violations):
    return [v.detail for v in violations]


def test_contiguous_passes(good_repo):
    assert check_migration_contiguity(good_repo) == []


def test_all_violations_are_error_severity_and_named(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=["0001_a", "0003_c"])
    violations = check_migration_contiguity(root)
    assert violations
    assert all(v.check == MIGRATION_CONTIGUITY for v in violations)
    assert all(v.severity == "error" for v in violations)


def test_gap_detected(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=["0001_a", "0002_b", "0004_d"])
    violations = check_migration_contiguity(root)
    assert any("0003" in d for d in details(violations))


def test_does_not_start_at_one(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=["0002_b", "0003_c"])
    violations = check_migration_contiguity(root)
    assert any("starts at 0002" in d for d in details(violations))


def test_duplicate_number(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=["0001_a", "0002_b", "0002_dup"])
    violations = check_migration_contiguity(root)
    assert any("duplicate migration number 0002" in d for d in details(violations))


def test_non_numeric_prefix(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=["0001_a", "readme_notes"])
    violations = check_migration_contiguity(root)
    assert any("no numeric prefix" in d for d in details(violations))


def test_missing_directory(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    import shutil

    shutil.rmtree(root / "schema" / "migrations")
    violations = check_migration_contiguity(root)
    assert any("migrations directory not found" in d for d in details(violations))


def test_empty_directory(tmp_path, repo_builder):
    root = repo_builder(tmp_path, migrations=[])
    violations = check_migration_contiguity(root)
    assert any("no numbered migration files" in d for d in details(violations))
