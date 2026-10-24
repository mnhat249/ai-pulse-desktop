from __future__ import annotations

import html
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.models import Digest
from app.pipeline.llm import LLMClient

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "digest_vi.txt"
SCHEMA_RETRIES = 1  # sai schema thì thử lại 1 lần


@dataclass(frozen=True)
class ClusterInput:
    cluster_id: int
    sources: list[str]
    titles: list[str]
    text: str


@dataclass(frozen=True)
class Provider:
    client: LLMClient
    daily_cap: int


QuotaCheck = Callable[[str, int], Awaitable[bool]]
RecordCall = Callable[[str], Awaitable[None]]


def load_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _escape(text: str) -> str:
    """Nội dung bài là dữ liệu của người lạ: không để nó tự đóng thẻ hay mở thẻ <su_kien> giả."""
    return html.escape(text, quote=False)


def render_clusters(batch: list[ClusterInput], max_text_chars: int) -> str:
    blocks = []
    for c in batch:
        blocks.append(
            f'<su_kien cluster_id="{int(c.cluster_id)}">\n'
            f"Nguồn: {_escape(', '.join(c.sources))}\n"
            f"Tiêu đề: {_escape(' | '.join(c.titles))}\n"
            f"Nội dung: {_escape(c.text[:max_text_chars])}\n"
            "</su_kien>"
        )
    return "\n\n".join(blocks)


def build_prompt(template: str, batch: list[ClusterInput], max_text_chars: int) -> str:
    return template.replace("{su_kien}", render_clusters(batch, max_text_chars))


def parse_digests(raw: str, allowed_ids: set[int]) -> list[Digest]:
    """Chỉ nhận phần tử đúng schema `Digest` và đúng cluster_id của lô; còn lại bỏ."""
    data: Any = json.loads(raw)
    entries = data.get("items") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("JSON không có danh sách 'items'")
    digests: dict[int, Digest] = {}
    for entry in entries:
        try:
            digest = Digest.model_validate(entry)
        except ValidationError as exc:
            logger.warning("Bỏ phần tử sai schema: %s", exc.errors(include_url=False)[:1])
            continue
        if digest.cluster_id in allowed_ids:
            digests.setdefault(digest.cluster_id, digest)
    return list(digests.values())


async def digest_batch(
    providers: list[Provider],
    batch: list[ClusterInput],
    prompt_template: str,
    max_text_chars: int,
    quota_ok: QuotaCheck,
    record_call: RecordCall,
) -> list[Digest]:
    """Một lần gọi LLM cho cả lô (cả điểm rác lẫn tóm tắt).

    Thứ tự dự phòng: Gemini -> Groq. Hết quota hoặc lỗi mạng thì sang nhà cung cấp kế tiếp;
    sai schema thì thử lại 1 lần, vẫn sai thì cũng sang nhà cung cấp kế tiếp. Không ai trả lời
    được thì trả về danh sách rỗng và các cụm vẫn "chờ tóm tắt" (widget hiện tiêu đề gốc).
    """
    prompt = build_prompt(prompt_template, batch, max_text_chars)
    allowed = {c.cluster_id for c in batch}
    for provider in providers:
        name = provider.client.name
        if not await quota_ok(name, provider.daily_cap):
            logger.info("Hết trần quota hôm nay của %s, chuyển nhà cung cấp khác", name)
            continue
        for attempt in range(SCHEMA_RETRIES + 1):
            await record_call(name)
            try:
                raw = await provider.client.complete(prompt)
            except Exception as exc:
                logger.warning("%s lỗi: %r; chuyển nhà cung cấp khác", name, exc)
                break
            try:
                digests = parse_digests(raw, allowed)
            except ValueError as exc:
                logger.warning("%s trả về sai schema (lần %d): %s", name, attempt + 1, exc)
                continue
            if digests:
                return digests
            logger.warning("%s không có phần tử hợp lệ nào (lần %d)", name, attempt + 1)
        else:
            logger.warning("%s sai schema liên tục, thử nhà cung cấp kế tiếp", name)
    return []
