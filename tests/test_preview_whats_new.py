import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preview_whats_new as pw


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def page(title, tags='["a"]'):
    return f'---\ntitle: "{title}"\ntags: {tags}\n---\n\nBody\n'


def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "content/01_Timeline").mkdir(parents=True)
    (tmp_path / "content/01_Timeline/old.md").write_text(page("Old"))
    (tmp_path / "content/01_Timeline/same.md").write_text(page("Same"))
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "base"); git(tmp_path, "branch", "base")
    git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "content/01_Timeline/old.md").write_text(page("Old", "[]") + "more\n")
    (tmp_path / "content/01_Timeline/new.md").write_text(page("New | One"))
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "feature")
    monkeypatch.chdir(tmp_path)


def test_new_and_changed_pages_are_tagged_and_listed(tmp_path, monkeypatch):
    repo(tmp_path, monkeypatch)
    changes = pw.build("base")
    assert changes == {"A": ["content/01_Timeline/new.md"], "M": ["content/01_Timeline/old.md"]}
    new = (tmp_path / "content/01_Timeline/new.md").read_text()
    assert '"preview-new"' in new and "[!info] New in this preview" in new and "Body" in new
    assert 'tags: ["preview-changed"]' in (tmp_path / "content/01_Timeline/old.md").read_text()
    assert "preview" not in (tmp_path / "content/01_Timeline/same.md").read_text()
    listing = (tmp_path / "content/00_Meta/Whats_New.md").read_text()
    assert "[[01_Timeline/new|New / One]]" in listing and "[[01_Timeline/old|Old]]" in listing


def test_branch_equal_to_base_says_so(tmp_path, monkeypatch):
    repo(tmp_path, monkeypatch)
    git(tmp_path, "checkout", "base")
    pw.build("base")
    assert "no page differences" in (tmp_path / "content/00_Meta/Whats_New.md").read_text()


def test_quick_preview_keeps_only_new_changed_home_and_whats_new(tmp_path, monkeypatch):
    repo(tmp_path, monkeypatch)
    (tmp_path / "content/index.md").write_text(page("Home"))
    changes = pw.build("base")
    assert pw.prune(changes) == 1  # only "same.md" goes
    left = sorted(str(f.relative_to(tmp_path)) for f in (tmp_path / "content").rglob("*.md"))
    assert left == ["content/00_Meta/Whats_New.md", "content/01_Timeline/new.md",
                    "content/01_Timeline/old.md", "content/index.md"]
