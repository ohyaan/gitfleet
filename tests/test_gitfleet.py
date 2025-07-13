import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import shutil
import tempfile
import pytest
from gitfleet import Repository, ConfigLoader, FleetManager


def make_temp_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file1.txt").write_text("hello1")
    (repo_dir / "dir2").mkdir()
    (repo_dir / "dir2" / "file2.txt").write_text("hello2")
    return repo_dir


def test_repository_copy(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    working_dir = tmp_path
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"repoPath": "file1.txt", "dest": "copied/file1.txt"},
            {"repoPath": "dir2", "dest": "copied/dir2"},
        ],
    }
    repo = Repository(config, str(working_dir), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()
    copied_file = working_dir / "copied" / "file1.txt"
    assert copied_file.exists()
    assert copied_file.read_text() == "hello1"
    copied_dir_file = working_dir / "copied" / "dir2" / "file2.txt"
    assert copied_dir_file.exists()
    assert copied_dir_file.read_text() == "hello2"


def test_repository_copy_missing_source(tmp_path, caplog):
    repo_dir = make_temp_repo(tmp_path)
    working_dir = tmp_path
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"repoPath": "notfound.txt", "dest": "copied/notfound.txt"},
        ],
    }
    repo = Repository(config, str(working_dir), dry_run=False)
    repo.dest_path = str(repo_dir)
    with caplog.at_level("WARNING"):
        repo.perform_copy_operations()
    assert any("Source path does not exist" in r for r in caplog.text.splitlines())


def test_repository_copy_dry_run(tmp_path, caplog):
    repo_dir = make_temp_repo(tmp_path)
    working_dir = tmp_path
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"repoPath": "file1.txt", "dest": "copied/file1.txt"},
        ],
    }
    repo = Repository(config, str(working_dir), dry_run=True)
    repo.dest_path = str(repo_dir)
    with caplog.at_level("INFO"):
        repo.perform_copy_operations()
    assert any("Would copy" in r for r in caplog.text.splitlines())


def test_config_loader_and_validation(tmp_path):
    config = {
        "schemaVersion": "v1",
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "refs/heads/main",
            }
        ],
    }
    config_path = tmp_path / "fleet.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    loaded = ConfigLoader.load_config(str(config_path))
    assert loaded["schemaVersion"] == "v1"
    assert loaded["repositories"][0]["src"].startswith("https://github.com/")


def test_fleet_manager_find_config(tmp_path):
    config = {"schemaVersion": "v1", "repositories": []}
    for name in ["gitfleet.yaml", "gitfleet.yml", "gitfleet.json"]:
        config_path = tmp_path / name
        with open(config_path, "w") as f:
            f.write("schemaVersion: v1\nrepositories: []\n")
        found = FleetManager.find_fleet_config_file(str(tmp_path))
        assert found.endswith(name)
        config_path.unlink()


def test_revision_type_detection():
    from gitfleet import GitRunner, RevisionType

    assert GitRunner.detect_revision_type("refs/heads/main")[0] == RevisionType.HEADS
    assert GitRunner.detect_revision_type("refs/tags/v1.2.3")[0] == RevisionType.TAGS
    assert (
        GitRunner.detect_revision_type("a1b2c3d4e5f67890abcdef1234567890abcdef12")[0]
        == RevisionType.SHA1
    )
    assert GitRunner.detect_revision_type("unknown")[0] == RevisionType.SHA1


def test_shallow_clone_flag(tmp_path, monkeypatch):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "shallow-clone": True,
    }
    repo = Repository(config, str(tmp_path), dry_run=True)
    # Patch GitRunner to check options
    called = {}

    def fake_run_command(cmd, **kwargs):
        called["cmd"] = cmd
        return ""

    monkeypatch.setattr("gitfleet.GitRunner.run_command", fake_run_command)
    repo.clone()
    assert "--depth" in called["cmd"]


def test_clone_submodule_flag(tmp_path, monkeypatch):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "clone-submodule": True,
    }
    repo = Repository(config, str(tmp_path), dry_run=True)
    called = {"cmds": []}

    def fake_run_command(cmd, **kwargs):
        called["cmds"].append(cmd)
        return ""

    monkeypatch.setattr("gitfleet.GitRunner.run_command", fake_run_command)
    repo.clone()
    assert any("submodule" in c for c in called["cmds"])


def test_clone_subfleet_flag(tmp_path, monkeypatch):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "clone-subfleet": True,
    }
    repo = Repository(config, str(tmp_path), dry_run=True)
    # Patch FleetManager.find_fleet_config_file to simulate nested fleet
    monkeypatch.setattr(
        "gitfleet.FleetManager.find_fleet_config_file",
        lambda path: str(tmp_path / "dummy.yaml"),
    )

    class DummyFleetManager(FleetManager):
        called = False

        def __init__(self, *a, **k):
            pass

        def process(self):
            DummyFleetManager.called = True

    monkeypatch.setattr("gitfleet.FleetManager", DummyFleetManager)
    repo.process_subfleet()
    assert DummyFleetManager.called


def test_anchor_updates_revision(tmp_path, monkeypatch):
    # Simulate a repo with a current SHA1
    config = {
        "schemaVersion": "v1",
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "refs/heads/main",
            }
        ],
    }
    # 必要なfleet configファイルを作成
    config_path = tmp_path / "gitfleet.yaml"
    with open(config_path, "w") as f:
        f.write(
            "schemaVersion: v1\nrepositories:\n- src: https://github.com/example/repo.git\n  dest: repo\n  revision: refs/heads/main\n"
        )
    fm = FleetManager(str(tmp_path), dry_run=True)
    fm.load()
    # Patch get_current_sha1
    for repo in fm.repositories:
        repo.get_current_sha1 = lambda: "deadbeefdeadbeef"
    fm.anchor()
    assert fm.config["repositories"][0]["revision"].startswith("deadbeef")


def test_release_asset_extract(tmp_path, monkeypatch):
    from gitfleet import ReleaseAsset

    # Create a fake zip file
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    import zipfile

    zip_path = dest_dir / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("foo.txt", "bar")
    config = {"name": "test.zip", "dest": str(dest_dir), "extract": True}
    asset = ReleaseAsset(config, str(tmp_path), dry_run=False)
    asset.file_path = str(zip_path)
    assert asset.extract()
    assert (dest_dir / "foo.txt").exists()


def test_release_asset_no_extract(tmp_path):
    from gitfleet import ReleaseAsset

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    file_path = dest_dir / "plain.txt"
    file_path.write_text("plain")
    config = {"name": "plain.txt", "dest": str(dest_dir), "extract": False}
    asset = ReleaseAsset(config, str(tmp_path), dry_run=False)
    asset.file_path = str(file_path)
    assert asset.extract()


def test_release_sync_download(monkeypatch, tmp_path):
    from gitfleet import Release

    # Patch fetch_release_info and find_asset_download_url
    class DummyAsset:
        def __init__(self, *a, **k):
            self.name = "foo.txt"
            self.downloaded = False
            self.extracted = False

        def download(self, url):
            self.downloaded = True
            return True

        def extract(self):
            self.extracted = True
            return True

    class DummyRelease(Release):
        def setup_assets(self):
            self.assets = [DummyAsset(None, None)]

        def fetch_release_info(self):
            return {
                "assets": [
                    {
                        "name": "foo.txt",
                        "browser_download_url": "http://example.com/foo.txt",
                    }
                ]
            }

        def find_asset_download_url(self, name, data):
            return "http://example.com/foo.txt"

    config = {
        "url": "https://github.com/example/repo",
        "tag": "v1.0.0",
        "assets": [{"name": "foo.txt", "dest": "dest"}],
    }
    rel = DummyRelease(config, str(tmp_path), dry_run=True)
    assert rel.sync()


def test_config_loader_missing_required_fields(tmp_path):
    # Missing 'src'
    config = {
        "schemaVersion": "v1",
        "repositories": [{"dest": "repo", "revision": "refs/heads/main"}],
    }
    config_path = tmp_path / "fleet.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    with pytest.raises(Exception) as e:
        ConfigLoader.load_config(str(config_path))
    assert "missing required field" in str(e.value)

    # Missing 'repositories' and 'releases'
    config = {"schemaVersion": "v1"}
    config_path = tmp_path / "fleet2.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    with pytest.raises(Exception) as e:
        ConfigLoader.load_config(str(config_path))
    assert "must contain 'repositories' or 'releases'" in str(e.value)


def test_config_loader_invalid_types(tmp_path):
    # clone-submodule is not bool
    config = {
        "schemaVersion": "v1",
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "refs/heads/main",
                "clone-submodule": "yes",
            }
        ],
    }
    config_path = tmp_path / "fleet.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    with pytest.raises(Exception) as e:
        ConfigLoader.load_config(str(config_path))
    assert "must be a boolean value" in str(e.value)


def test_copy_entry_missing_fields(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"dest": "copied/file1.txt"},  # missing repoPath
            {"repoPath": "file1.txt"},  # missing dest
        ],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    # Should not raise, but should warn and skip
    repo.perform_copy_operations()
    # No file should be copied
    assert not (tmp_path / "copied" / "file1.txt").exists()


def test_copy_to_existing_file(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    dest_file = tmp_path / "copied"
    dest_file.write_text("old")
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"repoPath": "file1.txt", "dest": "copied"},
        ],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()
    # Should overwrite file with new content
    assert dest_file.read_text() == "hello1"


def test_release_asset_extract_unsupported(tmp_path):
    from gitfleet import ReleaseAsset

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    file_path = dest_dir / "file.7z"
    file_path.write_text("dummy")
    config = {"name": "file.7z", "dest": str(dest_dir), "extract": True}
    asset = ReleaseAsset(config, str(tmp_path), dry_run=False)
    asset.file_path = str(file_path)
    # Should not extract, but should not fail
    assert asset.extract()


def test_release_asset_download_error(monkeypatch, tmp_path):
    from gitfleet import ReleaseAsset

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    config = {"name": "file.txt", "dest": str(dest_dir)}
    asset = ReleaseAsset(config, str(tmp_path), dry_run=False)
    asset.file_path = str(dest_dir / "file.txt")

    def fake_urlopen(*a, **k):
        raise Exception("Download failed")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert not asset.download("http://example.com/file.txt")


def test_dry_run_no_filesystem_change(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [
            {"repoPath": "file1.txt", "dest": "copied/file1.txt"},
        ],
    }
    repo = Repository(config, str(tmp_path), dry_run=True)
    repo.dest_path = str(repo_dir)
    before = set(os.listdir(tmp_path))
    repo.perform_copy_operations()
    after = set(os.listdir(tmp_path))
    assert before == after


def test_config_loader_schema_version(tmp_path):
    # schemaVersion missing
    config = {
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "refs/heads/main",
            }
        ]
    }
    config_path = tmp_path / "fleet.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    loaded = ConfigLoader.load_config(str(config_path))
    assert "schemaVersion" not in loaded or loaded["schemaVersion"] is None

    # schemaVersion invalid
    config = {
        "schemaVersion": "v2",
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "refs/heads/main",
            }
        ],
    }
    config_path = tmp_path / "fleet2.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    loaded = ConfigLoader.load_config(str(config_path))
    assert loaded["schemaVersion"] == "v2"


def test_revision_invalid_format(tmp_path):
    config = {
        "schemaVersion": "v1",
        "repositories": [
            {
                "src": "https://github.com/example/repo.git",
                "dest": "repo",
                "revision": "",
            }
        ],
    }
    config_path = tmp_path / "fleet.json"
    with open(config_path, "w") as f:
        import json

        json.dump(config, f)
    # 空文字は許容されるが、実際のgit操作で失敗するはず。ここでは例外は発生しないことを確認
    loaded = ConfigLoader.load_config(str(config_path))
    assert loaded["repositories"][0]["revision"] == ""


def test_copy_empty_and_none(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    # copy: []
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()  # Should do nothing, not fail
    # copy: None
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": None,
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()  # Should do nothing, not fail


def test_copy_file_to_dir_and_dir_to_file(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    # file to dir
    dest_dir = tmp_path / "dest_dir"
    dest_dir.mkdir()
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [{"repoPath": "file1.txt", "dest": str(dest_dir)}],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()
    # Should copy file1.txt into dest_dir/file1.txt
    assert (dest_dir / "file1.txt").exists()
    # dir to file (should fail gracefully)
    dest_file = tmp_path / "dest_file"
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [{"repoPath": "dir2", "dest": str(dest_file)}],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    repo.perform_copy_operations()  # Should warn and not raise


def test_copy_permission_error(tmp_path, monkeypatch):
    repo_dir = make_temp_repo(tmp_path)
    dest_dir = tmp_path / "no_perm"
    dest_dir.mkdir()
    dest_file = dest_dir / "file1.txt"
    dest_dir.chmod(0o400)  # read-only
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [{"repoPath": "file1.txt", "dest": str(dest_file)}],
    }
    repo = Repository(config, str(tmp_path), dry_run=False)
    repo.dest_path = str(repo_dir)
    # Should log error, not raise
    repo.perform_copy_operations()
    dest_dir.chmod(0o700)  # restore permissions for cleanup


def test_release_asset_extract_invalid_type(tmp_path):
    from gitfleet import ReleaseAsset

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    file_path = dest_dir / "plain.txt"
    file_path.write_text("plain")
    config = {"name": "plain.txt", "dest": str(dest_dir), "extract": "yes"}
    asset = ReleaseAsset(config, str(tmp_path), dry_run=False)
    asset.file_path = str(file_path)
    # Should treat as True (Python bool("yes") is True), so extract not needed, should not fail
    assert asset.extract()


def test_release_url_not_github(tmp_path):
    from gitfleet import Release

    config = {
        "url": "https://gitlab.com/example/repo",
        "tag": "v1.0.0",
        "assets": [{"name": "foo.txt", "dest": "dest"}],
    }
    with pytest.raises(Exception) as e:
        Release(config, str(tmp_path), dry_run=True)
    assert "Only GitHub URLs are supported" in str(e.value)


def test_release_tag_not_found(monkeypatch, tmp_path):
    from gitfleet import Release

    class DummyRelease(Release):
        def fetch_release_info(self):
            raise Exception("Not found")

    config = {
        "url": "https://github.com/example/repo",
        "tag": "v1.0.0",
        "assets": [{"name": "foo.txt", "dest": "dest"}],
    }
    rel = DummyRelease(config, str(tmp_path), dry_run=True)
    with pytest.raises(Exception) as e:
        rel.sync()
    assert "Not found" in str(e.value)


def test_dry_run_filesystem_integrity(tmp_path):
    repo_dir = make_temp_repo(tmp_path)
    config = {
        "src": "https://github.com/example/repo.git",
        "dest": str(repo_dir),
        "revision": "refs/heads/main",
        "copy": [{"repoPath": "file1.txt", "dest": "copied/file1.txt"}],
    }
    repo = Repository(config, str(tmp_path), dry_run=True)
    repo.dest_path = str(repo_dir)
    before = {p.name: p.stat().st_mtime for p in tmp_path.iterdir()}
    repo.perform_copy_operations()
    after = {p.name: p.stat().st_mtime for p in tmp_path.iterdir()}
    assert before == after
