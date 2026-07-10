import subprocess

import pytest

from rainspout.devtools.version_bump import check_repo, is_stage_code, main, stage_dir_of


def git(repo, *args):
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.test")
    git(tmp_path, "config", "user.name", "ci")
    stage = tmp_path / "src" / "pkg" / "stages" / "smooth"
    stage.mkdir(parents=True)
    (stage / "stage.py").write_text('version = "1.0.0"\nCODE = 1\n')
    (stage / "science.py").write_text("def f():\n    return 1\n")
    (stage / "test_smooth.py").write_text("def test_ok():\n    assert True\n")
    fixtures = stage / "fixtures"
    fixtures.mkdir()
    (fixtures / "gen.py").write_text("F = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "branch", "base")
    return tmp_path


def commit_all(repo_path):
    git(repo_path, "add", ".")
    git(repo_path, "commit", "-q", "-m", "change")


def test_code_change_without_bump_fails(repo):
    (repo / "src/pkg/stages/smooth/science.py").write_text("def f():\n    return 2\n")
    commit_all(repo)
    assert check_repo(repo, "base") == ["src/pkg/stages/smooth"]
    assert main(["--base", "base", "--repo", str(repo)]) == 1


def test_code_change_with_bump_passes(repo):
    (repo / "src/pkg/stages/smooth/science.py").write_text("def f():\n    return 2\n")
    (repo / "src/pkg/stages/smooth/stage.py").write_text('version = "1.0.1"\nCODE = 1\n')
    commit_all(repo)
    assert check_repo(repo, "base") == []
    assert main(["--base", "base", "--repo", str(repo)]) == 0


def test_test_and_fixture_changes_exempt(repo):
    (repo / "src/pkg/stages/smooth/test_smooth.py").write_text("def test_ok():\n    pass\n")
    (repo / "src/pkg/stages/smooth/fixtures/gen.py").write_text("F = 2\n")
    commit_all(repo)
    assert check_repo(repo, "base") == []


def test_new_stage_with_version_passes(repo):
    new = repo / "src/pkg/stages/fresh"
    new.mkdir()
    (new / "stage.py").write_text('version = "0.1.0"\n')
    commit_all(repo)
    assert check_repo(repo, "base") == []


def test_new_code_file_without_bump_fails(repo):
    (repo / "src/pkg/stages/smooth/extra.py").write_text("MORE = 1\n")
    commit_all(repo)
    assert check_repo(repo, "base") == ["src/pkg/stages/smooth"]


def test_path_heuristics():
    assert stage_dir_of("src/pkg/stages/smooth/science.py") == "src/pkg/stages/smooth"
    assert stage_dir_of("src/pkg/stages/smooth/deep/util.py") == "src/pkg/stages/smooth"
    assert stage_dir_of("src/pkg/handlers/x/handler.py") is None
    assert stage_dir_of("src/pkg/stages/loose.py") is None
    assert is_stage_code("src/pkg/stages/smooth/science.py")
    assert not is_stage_code("src/pkg/stages/smooth/test_x.py")
    assert not is_stage_code("src/pkg/stages/smooth/x_test.py")
    assert not is_stage_code("src/pkg/stages/smooth/fixtures/gen.py")
    assert not is_stage_code("src/pkg/stages/smooth/example_data/make.py")
    assert not is_stage_code("src/pkg/stages/smooth/notes.md")
