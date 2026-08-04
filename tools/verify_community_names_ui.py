#!/usr/bin/env python3
"""Verify reviewed community display names in the live frontend DOM."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


HANDOFF_DIR = Path(__file__).resolve().parents[1]
NAMES_PATH = (
    HANDOFF_DIR
    / "platform"
    / "frontend"
    / "src"
    / "data"
    / "community-names-20260715.json"
)
BASE_URL = "http://127.0.0.1:3000"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    payload = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    expected_names = {int(cid): name for cid, name in payload["names"].items()}
    require(payload.get("version") == "2026-07-16", "unexpected naming version")
    require(len(expected_names) == 40, "expected exactly 40 reviewed names")

    page_errors: list[str] = []
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto(f"{BASE_URL}/topics", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=分群列表")

        communities_response = page.request.get(f"{BASE_URL}/api/communities")
        require(communities_response.ok, "communities API request failed")
        visible_ids = {
            int(item["community"])
            for item in communities_response.json()
            if int(item.get("size", 0)) >= 10
        }
        require(
            visible_ids == set(expected_names),
            f"major-community ID mismatch: api={sorted(visible_ids)}",
        )

        topic_text = page.locator("body").inner_text()
        missing_topic_ids = [
            cid
            for cid, name in expected_names.items()
            if f"{name} (#{cid})" not in topic_text
        ]
        require(not missing_topic_ids, f"topic page missing IDs: {missing_topic_ids}")

        page.goto(f"{BASE_URL}/skill-tree", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=探索性圖結構導覽")

        paths_response = page.request.get(f"{BASE_URL}/api/learning-paths/communities")
        require(paths_response.ok, "community learning-path API request failed")
        paths_payload = paths_response.json()
        groups = paths_payload if isinstance(paths_payload, list) else paths_payload.get("groups", [])
        skill_ids = {
            int(group["community"])
            for group in groups
            if int(group.get("size", len(group.get("nodes", [])))) >= 10
        }
        require(skill_ids, "skill tree returned no visible major communities")

        skill_text = page.locator("body").inner_text()
        missing_skill_ids = [
            cid for cid in sorted(skill_ids) if expected_names.get(cid) not in skill_text
        ]
        require(not missing_skill_ids, f"skill tree missing IDs: {missing_skill_ids}")

        browser.close()

    require(not page_errors, f"page errors: {page_errors}")
    require(not console_errors, f"console errors: {console_errors}")
    print(
        json.dumps(
            {
                "status": "ok",
                "naming_version": payload["version"],
                "topic_names_verified": len(visible_ids),
                "skill_tree_names_verified": len(skill_ids),
                "page_errors": len(page_errors),
                "console_errors": len(console_errors),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
