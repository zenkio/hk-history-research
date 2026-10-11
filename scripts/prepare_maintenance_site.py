#!/usr/bin/env python3
"""Create a maintenance-only static site without touching source/history data."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def prepare_site(output_dir: Path, page_path: Path, robots_path: Path, cname_path: Path) -> None:
    # Guard against accidentally pointing the destructive cleanup at the repository.
    if output_dir.is_symlink():
        raise ValueError("Refusing to replace a symlink as the output directory")
    output = output_dir.resolve()
    if output.name != "public" or output == Path(output.anchor):
        raise ValueError("Output must be a dedicated directory named 'public'")

    page = page_path.read_text(encoding="utf-8")
    if '<meta name="robots" content="noindex, nofollow">' not in page.lower():
        raise ValueError("Maintenance page must include robots noindex, nofollow")

    robots = robots_path.read_text(encoding="utf-8")
    # The history sitemap is deliberately absent while all historical pages are unavailable.
    robots = "\n".join(
        line for line in robots.splitlines()
        if not line.strip().lower().startswith("sitemap:")
    ).rstrip() + "\n"

    cname = cname_path.read_text(encoding="utf-8").strip()
    if not cname or any(char.isspace() for char in cname):
        raise ValueError("CNAME must contain one hostname")

    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()

    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "robots.txt").write_text(robots, encoding="utf-8")
    (output / "CNAME").write_text(cname + "\n", encoding="utf-8")

    expected = {"index.html", "robots.txt", "CNAME"}
    actual = {child.name for child in output.iterdir()}
    if actual != expected:
        raise RuntimeError(f"Maintenance output is not allow-listed: {sorted(actual)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--page", type=Path, default=Path("site/maintenance.html"))
    parser.add_argument("--robots", type=Path, default=Path("site/robots.txt"))
    parser.add_argument("--cname", type=Path, default=Path("site/CNAME"))
    args = parser.parse_args()
    prepare_site(args.output, args.page, args.robots, args.cname)
    print("Maintenance-only site prepared; historical pages, feeds and search indexes are excluded.")


if __name__ == "__main__":
    main()
