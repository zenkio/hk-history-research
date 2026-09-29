"""Checks on the real repository: config files and every published page (no network)."""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_models_json_routing_names_real_models():
    cfg = json.load(open(os.path.join(ROOT, "scripts", "models.json"), encoding="utf-8"))
    models = {m["display"] for m in cfg["models"]}
    for role, names in cfg["routing"].items():
        if role.startswith("_"):
            continue
        missing = [n for n in names if n not in models]
        assert not missing, f"routing '{role}' names unknown models {missing}"


def test_workflows_are_valid_yaml():
    yaml = __import__("yaml")
    for path in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")):
        assert isinstance(yaml.safe_load(open(path, encoding="utf-8")), dict), path


def workflow(name):
    yaml = __import__("yaml")
    return yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8"))


def test_public_pipeline_log_never_shows_script_output():
    # This repository is public, so its run logs are too; the pipeline's output names pages, queries
    # and grades. Every script step must send its output to $LOG (saved to the private data repo).
    steps = workflow("ingestion.yml")["jobs"]["pipeline"]["steps"]
    runs = [s["run"] for s in steps if "python3 scripts/" in s.get("run", "")]
    assert len(runs) == 4
    for run in runs:
        assert run.rstrip().endswith('>> "$LOG" 2>&1'), run


def test_pipeline_is_off_unless_switched_on():
    # It runs either on Actions or on our own machine, never both (same quota, same branch).
    assert workflow("ingestion.yml")["jobs"]["pipeline"]["if"] == \
        "github.event_name != 'schedule' || vars.PIPELINE_ON_ACTIONS == 'on'"


def test_workflows_publish_nothing_but_the_built_site():
    # Artifacts of a public repository can be downloaded by anyone: only the built site may be uploaded.
    for path in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")):
        for job in workflow(os.path.basename(path))["jobs"].values():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if "upload" in uses:
                    assert uses.startswith("actions/upload-pages-artifact"), (path, uses)


def test_licence_keeps_quartz_mit_and_reserves_the_rest():
    assert "MIT License" in open(os.path.join(ROOT, "quartz", "LICENSE.txt"), encoding="utf-8").read()
    assert "All rights reserved" in open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
    assert not os.path.exists(os.path.join(ROOT, "LICENSE.txt")), "a root MIT licence makes GitHub label the whole repo MIT"
    assert json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))["license"] == "UNLICENSED"


PIPELINE_DIRS = ("01_Timeline", "02_Entities", "03_Angles", "04_Unverified", "zh")


def pages():
    """Pages the pipeline writes (the hand-written guides in content/Guides etc. are not checked)."""
    return [p for d in PIPELINE_DIRS for p in glob.glob(os.path.join(ROOT, "content", d, "**", "*.md"), recursive=True)]


def test_every_page_has_front_matter_and_title():
    bad = []
    for path in pages():
        text = open(path, encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not m or not re.search(r"^title:\s*\S", m.group(1), re.M):
            bad.append(os.path.relpath(path, ROOT))
    assert not bad, f"{len(bad)} pages without front matter or title, e.g. {bad[:5]}"


def test_evidence_grades_are_valid():
    bad = [os.path.relpath(p, ROOT) for p in pages()
           if (m := re.search(r"^evidence_grade:\s*(.*)$", open(p, encoding="utf-8").read(), re.M))
           and m.group(1).strip() not in ("A", "B", "none")]
    assert not bad, f"invalid evidence_grade in {bad[:5]}"


def test_public_repo_ignores_every_data_path():
    # The code is copied over the private data to run; nothing from the data may ever be committed here.
    ignored = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read().split()
    for path in ("content/", "research/", "04_Ingestion_Queue/", "scripts/state/", "scripts/seed_plan.json",
                 "scripts/quota_state.json", "BACKLOG.md", "PRODUCT.md", "logs/"):
        assert path in ignored, path


def test_site_address_is_the_custom_domain():
    # The site moved to its own domain (2026-09-28); baseUrl feeds the sitemap, RSS, previews and CNAME.
    cfg = open(os.path.join(ROOT, "quartz.config.default.yaml"), encoding="utf-8").read()
    assert re.search(r"^  baseUrl: hkhistory\.zenkio\.uk$", cfg, re.M)
