"""Render payloads as self-contained HTML pages (inline CSS + JS, hand-drawn SVG, no CDN)."""
from __future__ import annotations

import html
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("page_template.html")
INDEX_TEMPLATE = Path(__file__).with_name("index_template.html")
SCREENER_TEMPLATE = Path(__file__).with_name("screener_template.html")


def _embed(data: object) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # The JSON sits inside <script>: escape every "<" (only ever inside strings) as the valid JSON
    # escape <, so neither "</script" nor "<!--" in a value can end or confuse the block.
    return text.replace("<", "\\u003c")


def render(payload: dict) -> str:
    sector = payload["sector"]
    title = f"{sector['name']} 수출 × {sector['noun']} 실적"
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{DATA}}", _embed(payload)))


def render_index(summaries: list[dict], built_at: str) -> str:
    return (INDEX_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", "섹터별 수출 × 실적 겹쳐보기")
            .replace("{{DATA}}", _embed({"built_at": built_at, "sectors": summaries})))


def render_screener(payload: dict) -> str:
    return (SCREENER_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", "변곡점 레이더 — 통관 수출이 먼저 말하는 실적")
            .replace("{{DATA}}", _embed(payload)))
