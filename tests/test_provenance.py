from rainspout.provenance import hash_component_dir, provenance_entry, stage_code_hash


def make_tree(root):
    (root / "stage.py").write_text("class X: pass\n")
    (root / "science.py").write_text("def f(): return 1\n")
    (root / "test_stage.py").write_text("def test(): pass\n")
    (root / "helpers_test.py").write_text("def test2(): pass\n")
    (root / "fixtures").mkdir()
    (root / "fixtures" / "gen.py").write_text("FIXTURE = 1\n")
    (root / "example_data").mkdir()
    (root / "example_data" / "make.py").write_text("EXAMPLE = 1\n")


def test_hash_changes_with_code(tmp_path):
    make_tree(tmp_path)
    before = hash_component_dir(tmp_path)
    (tmp_path / "science.py").write_text("def f(): return 2\n")
    assert hash_component_dir(tmp_path) != before


def test_hash_ignores_test_territory(tmp_path):
    make_tree(tmp_path)
    before = hash_component_dir(tmp_path)
    (tmp_path / "test_stage.py").write_text("def test(): assert True\n")
    (tmp_path / "helpers_test.py").write_text("changed\n")
    (tmp_path / "fixtures" / "gen.py").write_text("FIXTURE = 2\n")
    (tmp_path / "example_data" / "make.py").write_text("EXAMPLE = 2\n")
    assert hash_component_dir(tmp_path) == before


def test_hash_sensitive_to_new_code_file(tmp_path):
    make_tree(tmp_path)
    before = hash_component_dir(tmp_path)
    (tmp_path / "extra.py").write_text("MORE = 1\n")
    assert hash_component_dir(tmp_path) != before


def test_stage_code_hash_stable_and_cached():
    from runner_components import RunScale

    first = stage_code_hash(RunScale)
    assert len(first) == 64
    assert stage_code_hash(RunScale) == first


def test_provenance_entry_shape():
    from runner_components import RunScale

    stage = RunScale({"factor": 2.0})
    entry = provenance_entry(stage, warnings=("clipped",))
    assert entry.stage_name == "run_scale"
    assert entry.stage_version == "1.2.0"
    assert entry.settings_used == {"factor": 2.0}
    assert entry.warnings == ("clipped",)
    assert entry.timestamp.tzinfo is not None
