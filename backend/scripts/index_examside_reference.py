"""Build a resumable ExamSIDE reconciliation index for GATE CSE papers.

ExamSIDE is a secondary transcription, not an authority for GATE questions or
answers.  This crawler therefore writes only to ``tmp/`` (ignored by Git),
marks every record as non-authoritative, and has no code path into the archive
importer or application question bank.

The SvelteKit data endpoint uses devalue's flattened JSON representation.  It
is decoded here with a small, bounded decoder: no ``eval``, no object hooks,
no dynamic imports, explicit reference bounds, depth/item limits, and blocked
prototype-related keys.

Raw responses can contain third-party explanation text.  They are cached only
under the ignored runtime directory for resumability.  The sanitized JSONL
never stores that text; it records only ``has_explanation`` and a SHA-256 of
the exact explanation value for reconciliation/deduplication.

Running without ``--paper`` or ``--all-papers`` performs discovery only.  A
small pilot can be run with, for example::

    python scripts/index_examside_reference.py \
        --paper gate-cse-2025-set-2 --max-questions 2

The full crawl requires the explicit ``--all-papers`` switch.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_DIR / "tmp"
DEFAULT_WORK_DIR = RUNTIME_ROOT / "pyq" / "reference" / "examside"
DEFAULT_INDEX_PATH = DEFAULT_WORK_DIR / "examside_reference_index.jsonl"

BASE_URL = "https://questions.examside.com"
YEAR_INDEX_URL = f"{BASE_URL}/past-years/year-wise/gate/gate-cse"
YEAR_INDEX_DATA_URL = f"{YEAR_INDEX_URL}/__data.json"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
DEFAULT_USER_AGENT = (
    "GatePath-Reconciliation-Indexer/1.0 "
    "(+https://github.com/icode100/gatepath; contact: repository issues)"
)

YEAR_MIN = 1996
YEAR_MAX = 2025
SOURCE_SITE = "ExamSIDE"
SOURCE_ROLE = "secondary_reconciliation_reference_only"
SCHEMA_VERSION = "1.0"

PAPER_SET_COUNTS: Mapping[int, int] = {
    2014: 3,
    2015: 3,
    2016: 2,
    2017: 2,
    2021: 2,
    2024: 2,
    2025: 2,
}
PAPER_SLUG_RE = re.compile(
    r"^gate-cse-(?P<year>19\d{2}|20\d{2})(?:-set-(?P<set>\d+))?$"
)
QUESTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,100}$", re.IGNORECASE)
BLOCKED_OBJECT_KEYS = frozenset({"__proto__", "prototype", "constructor"})


class ExamSideIndexError(RuntimeError):
    """Base error for the isolated reference indexer."""


class DevalueDecodeError(ExamSideIndexError):
    """Raised when a flattened payload is unsafe or malformed."""


class DiscoveryError(ExamSideIndexError):
    """Raised when the independently observed paper inventory is incomplete."""


class FetchError(ExamSideIndexError):
    """Raised when a public response cannot be fetched or validated."""


class RobotsDeniedError(FetchError):
    """Raised when the site's current robots policy disallows a URL."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: Any) -> str:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return _sha256_bytes(encoded)


def _atomic_write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def _atomic_write_json(path: Path, value: Any) -> None:
    body = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(path, body)


class _SafeDevalueDecoder:
    """Decode the bounded subset emitted by SvelteKit's devalue serializer."""

    _NEGATIVE_CONSTANTS: Mapping[int, Any] = {
        -1: None,  # undefined
        -2: None,  # array hole in an ordinary dense-array position
        -3: math.nan,
        -4: math.inf,
        -5: -math.inf,
        -6: -0.0,
    }

    def __init__(
        self,
        flattened: list[Any],
        *,
        max_nodes: int = 100_000,
        max_depth: int = 80,
        max_container_items: int = 250_000,
        max_string_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if not flattened:
            raise DevalueDecodeError("devalue payload is empty")
        if len(flattened) > max_nodes:
            raise DevalueDecodeError(
                f"devalue payload has {len(flattened)} nodes; limit is {max_nodes}"
            )
        self._flattened = flattened
        self._max_depth = max_depth
        self._max_container_items = max_container_items
        self._max_string_bytes = max_string_bytes
        self._memo: dict[int, Any] = {}
        self._active: set[int] = set()
        self._materialized_items = 0

    def decode(self) -> Any:
        return self._reference(0, 0)

    def _count(self, count: int) -> None:
        self._materialized_items += count
        if self._materialized_items > self._max_container_items:
            raise DevalueDecodeError("decoded payload exceeds the item limit")

    def _string(self, value: str) -> str:
        if len(value.encode("utf-8")) > self._max_string_bytes:
            raise DevalueDecodeError("decoded string exceeds the byte limit")
        return value

    def _safe_key(self, value: Any) -> str:
        if not isinstance(value, str):
            raise DevalueDecodeError("object key is not a string")
        self._string(value)
        if value.casefold() in BLOCKED_OBJECT_KEYS:
            raise DevalueDecodeError(f"blocked object key: {value}")
        return value

    def _reference(self, reference: int, depth: int) -> Any:
        if depth > self._max_depth:
            raise DevalueDecodeError("decoded payload exceeds the depth limit")
        if reference < 0:
            if reference not in self._NEGATIVE_CONSTANTS:
                raise DevalueDecodeError(f"unknown negative reference: {reference}")
            return self._NEGATIVE_CONSTANTS[reference]
        if reference >= len(self._flattened):
            raise DevalueDecodeError(
                f"reference {reference} is outside {len(self._flattened)} nodes"
            )
        if reference in self._memo:
            return self._memo[reference]
        if reference in self._active:
            raise DevalueDecodeError("cyclic devalue references are not accepted")

        self._active.add(reference)
        try:
            value = self._node(self._flattened[reference], depth + 1)
        finally:
            self._active.remove(reference)
        self._memo[reference] = value
        return value

    def _child(self, value: Any, depth: int) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return self._reference(value, depth)
        if isinstance(value, float):
            if not math.isfinite(value):
                raise DevalueDecodeError("non-finite inline number is not accepted")
            return value
        if isinstance(value, str):
            return self._string(value)
        if isinstance(value, (dict, list)):
            return self._node(value, depth + 1)
        raise DevalueDecodeError(f"unsupported encoded value: {type(value).__name__}")

    def _node(self, value: Any, depth: int) -> Any:
        if depth > self._max_depth:
            raise DevalueDecodeError("decoded payload exceeds the depth limit")
        if value is None or isinstance(value, bool):
            return value
        # A primitive number/string stored at a flattened index is a literal,
        # not another reference.
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise DevalueDecodeError("non-finite JSON number is not accepted")
            return value
        if isinstance(value, str):
            return self._string(value)
        if isinstance(value, dict):
            self._count(len(value))
            decoded: dict[str, Any] = {}
            for raw_key, raw_child in value.items():
                key = self._safe_key(raw_key)
                decoded[key] = self._child(raw_child, depth)
            return decoded
        if isinstance(value, list):
            self._count(len(value))
            if value and value[0] == -7:
                return self._sparse_array(value, depth)
            if value and isinstance(value[0], str):
                return self._tagged(value, depth)
            return [self._child(child, depth) for child in value]
        raise DevalueDecodeError(f"unsupported node value: {type(value).__name__}")

    def _sparse_array(self, value: list[Any], depth: int) -> list[Any]:
        """Decode devalue's bounded ``SPARSE_ARRAY`` representation."""

        if len(value) < 2 or not isinstance(value[1], int):
            raise DevalueDecodeError("sparse array is missing an integer length")
        length = value[1]
        if length < 0 or length > self._max_container_items:
            raise DevalueDecodeError("sparse array length is outside limits")
        encoded = value[2:]
        if len(encoded) % 2:
            raise DevalueDecodeError("sparse array has an incomplete index/value pair")
        self._count(length)
        decoded: list[Any] = [None] * length
        assigned: set[int] = set()
        for position in range(0, len(encoded), 2):
            index = encoded[position]
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < length
            ):
                raise DevalueDecodeError("sparse array index is outside its length")
            if index in assigned:
                raise DevalueDecodeError("sparse array index is repeated")
            assigned.add(index)
            decoded[index] = self._child(encoded[position + 1], depth)
        return decoded

    def _tagged(self, value: list[Any], depth: int) -> Any:
        tag = value[0]
        if tag == "Date" and len(value) == 2:
            return {"$type": "Date", "value": self._child(value[1], depth)}
        if tag == "BigInt" and len(value) == 2:
            integer = self._child(value[1], depth)
            if not isinstance(integer, str) or not re.fullmatch(r"-?\d+", integer):
                raise DevalueDecodeError("invalid BigInt representation")
            return {"$type": "BigInt", "value": integer}
        if tag == "RegExp" and len(value) in {2, 3}:
            pattern = self._child(value[1], depth)
            flags = self._child(value[2], depth) if len(value) == 3 else ""
            if not isinstance(pattern, str) or not isinstance(flags, str):
                raise DevalueDecodeError("invalid RegExp representation")
            return {"$type": "RegExp", "pattern": pattern, "flags": flags}
        if tag == "Set":
            return {
                "$type": "Set",
                "values": [self._child(child, depth) for child in value[1:]],
            }
        if tag == "Map":
            encoded = value[1:]
            if len(encoded) % 2:
                raise DevalueDecodeError("Map representation has an odd item count")
            return {
                "$type": "Map",
                "entries": [
                    [
                        self._child(encoded[index], depth),
                        self._child(encoded[index + 1], depth),
                    ]
                    for index in range(0, len(encoded), 2)
                ],
            }
        if tag == "null":
            encoded = value[1:]
            if len(encoded) % 2:
                raise DevalueDecodeError("null-prototype object has an odd item count")
            decoded: dict[str, Any] = {}
            for index in range(0, len(encoded), 2):
                key_value = encoded[index]
                if isinstance(key_value, int) and not isinstance(key_value, bool):
                    key_value = self._reference(key_value, depth)
                key = self._safe_key(key_value)
                decoded[key] = self._child(encoded[index + 1], depth)
            return decoded
        if tag == "Object" and len(value) == 2:
            return self._child(value[1], depth)
        raise DevalueDecodeError(f"unsupported devalue tag: {tag!r}")


def _validate_plain_json(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 80,
) -> None:
    if depth > max_depth:
        raise DevalueDecodeError("outer JSON exceeds the depth limit")
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, list):
        for child in value:
            _validate_plain_json(child, depth=depth + 1, max_depth=max_depth)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in BLOCKED_OBJECT_KEYS:
                raise DevalueDecodeError(f"blocked outer object key: {key!r}")
            _validate_plain_json(child, depth=depth + 1, max_depth=max_depth)
        return
    raise DevalueDecodeError(f"unsupported outer JSON value: {type(value).__name__}")


def decode_svelte_data(payload: bytes | str | Mapping[str, Any]) -> list[Any]:
    """Safely decode all data nodes in one SvelteKit ``__data.json`` payload."""

    if isinstance(payload, bytes):
        if len(payload) > 16 * 1024 * 1024:
            raise DevalueDecodeError("Svelte payload exceeds 16 MiB")
        parsed = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
            raise DevalueDecodeError("Svelte payload exceeds 16 MiB")
        parsed = json.loads(payload)
    else:
        parsed = dict(payload)
    _validate_plain_json(parsed)
    if parsed.get("type") != "data" or not isinstance(parsed.get("nodes"), list):
        raise DevalueDecodeError("response is not a SvelteKit data payload")
    if len(parsed["nodes"]) > 64:
        raise DevalueDecodeError("Svelte payload contains too many route nodes")

    decoded: list[Any] = []
    for node in parsed["nodes"]:
        if node is None:
            decoded.append(None)
            continue
        if not isinstance(node, dict):
            raise DevalueDecodeError("Svelte route node is not an object")
        if node.get("type") not in {"data", "skip"}:
            raise DevalueDecodeError(f"unsupported Svelte node type: {node.get('type')!r}")
        if "data" not in node:
            decoded.append(None)
            continue
        flattened = node["data"]
        if not isinstance(flattened, list):
            raise DevalueDecodeError("Svelte node data is not a flattened array")
        decoded.append(_SafeDevalueDecoder(flattened).decode())
    return decoded


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def expected_paper_slugs() -> tuple[str, ...]:
    """Return the 39 independent GATE CSE paper/session slugs for 1996-2025."""

    slugs: list[str] = []
    for year in range(YEAR_MAX, YEAR_MIN - 1, -1):
        set_count = PAPER_SET_COUNTS.get(year)
        if set_count:
            # The public year index orders the independent sessions Set 2/3
            # first.  Ordering has no authority significance.
            slugs.extend(
                f"gate-cse-{year}-set-{set_number}"
                for set_number in range(set_count, 0, -1)
            )
        else:
            slugs.append(f"gate-cse-{year}")
    return tuple(slugs)


@dataclass(frozen=True)
class PaperReference:
    slug: str
    year: int
    session: str
    title: str
    source_id: str | None
    url: str
    data_url: str

    @property
    def booklet_policy(self) -> str:
        if self.year == 2013:
            return "single_independent_paper_preserve_question_booklet_codes"
        return "not_applicable"


def discover_papers(decoded_nodes: Iterable[Any]) -> list[PaperReference]:
    """Discover and validate the exact independent 1996-2025 paper inventory."""

    candidates: dict[str, PaperReference] = {}
    for node in decoded_nodes:
        for item in _walk(node):
            slug = item.get("key")
            if not isinstance(slug, str):
                continue
            match = PAPER_SLUG_RE.fullmatch(slug)
            if not match:
                continue
            year = int(match.group("year"))
            if not YEAR_MIN <= year <= YEAR_MAX:
                continue
            set_number = match.group("set")
            session = f"set{set_number}" if set_number else "main"
            title = item.get("title")
            source_id = item.get("metaId")
            candidate = PaperReference(
                slug=slug,
                year=year,
                session=session,
                title=title if isinstance(title, str) else f"GATE CSE {year}",
                source_id=source_id if isinstance(source_id, str) else None,
                url=f"{YEAR_INDEX_URL}/{slug}",
                data_url=f"{YEAR_INDEX_URL}/{slug}/__data.json",
            )
            previous = candidates.get(slug)
            if previous and previous.source_id and candidate.source_id:
                if previous.source_id != candidate.source_id:
                    raise DiscoveryError(f"conflicting source IDs for {slug}")
            candidates[slug] = candidate

    expected = expected_paper_slugs()
    observed = set(candidates)
    missing = [slug for slug in expected if slug not in observed]
    unexpected = sorted(observed.difference(expected))
    if missing or unexpected:
        raise DiscoveryError(
            "ExamSIDE independent paper inventory differs from the audited "
            f"1996-2025 scope; missing={missing}, unexpected={unexpected}"
        )
    papers = [candidates[slug] for slug in expected]
    if len(papers) != 39:
        raise DiscoveryError(f"expected 39 independent papers; discovered {len(papers)}")
    if [paper.slug for paper in papers if paper.year == 2013] != ["gate-cse-2013"]:
        raise DiscoveryError("2013 booklet codes must remain one independent paper")
    return papers


Transport = Callable[
    [str, Mapping[str, str], float, int],
    tuple[int, Mapping[str, str], bytes, str],
]


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    body: bytes
    sha256: str
    retrieved_at: str
    cache_hit: bool


class HttpCacheClient:
    """Rate-limited retrying HTTP reader with an ignored raw-response cache."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_seconds: float = 1.5,
        max_retries: int = 4,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 16 * 1024 * 1024,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not user_agent.strip() or "GatePath" not in user_agent:
            raise ValueError("use a descriptive GatePath crawler user agent")
        if min_interval_seconds < 0:
            raise ValueError("minimum interval cannot be negative")
        if max_retries < 0:
            raise ValueError("maximum retries cannot be negative")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._transport = transport or self._urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def _validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "questions.examside.com":
            raise FetchError(f"refusing non-ExamSIDE URL: {url}")
        if parsed.username or parsed.password:
            raise FetchError("URL credentials are not accepted")

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        suffix = ".json" if url.endswith(".json") else ".txt"
        return (
            self.cache_dir / f"{digest}{suffix}",
            self.cache_dir / f"{digest}.metadata.json",
        )

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            wait = self.min_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_at = now

    def _urllib_transport(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes, str]:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            body = error.read(max_bytes + 1)
            return error.code, dict(error.headers.items()), body, error.geturl()
        with response:
            body = response.read(max_bytes + 1)
            return (
                int(response.status),
                dict(response.headers.items()),
                body,
                response.geturl(),
            )

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> float | None:
        raw = next(
            (value for key, value in headers.items() if key.casefold() == "retry-after"),
            None,
        )
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                moment = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())

    def fetch(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        self._validate_url(url)
        body_path, metadata_path = self._cache_paths(url)
        if body_path.exists() and not force_refresh:
            body = body_path.read_bytes()
            if len(body) > self.max_response_bytes:
                raise FetchError(f"cached response exceeds byte limit: {url}")
            metadata: dict[str, Any] = {}
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            digest = _sha256_bytes(body)
            expected_digest = metadata.get("sha256")
            if expected_digest and expected_digest != digest:
                raise FetchError(f"cached response checksum mismatch: {url}")
            retrieved_at = metadata.get("retrieved_at")
            if not isinstance(retrieved_at, str):
                retrieved_at = datetime.fromtimestamp(
                    body_path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat().replace("+00:00", "Z")
            final_url = metadata.get("final_url")
            if not isinstance(final_url, str):
                final_url = url
            self._validate_url(final_url)
            return FetchResult(url, final_url, body, digest, retrieved_at, True)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.1",
        }
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            try:
                status, response_headers, body, final_url = self._transport(
                    url,
                    headers,
                    self.timeout_seconds,
                    self.max_response_bytes,
                )
                self._validate_url(final_url)
            except (OSError, urllib.error.URLError, TimeoutError) as error:
                last_error = error
                status = 0
                response_headers = {}
                body = b""
                final_url = url

            if len(body) > self.max_response_bytes:
                raise FetchError(f"response exceeds byte limit: {url}")
            if status == 200:
                retrieved_at = _utc_now()
                digest = _sha256_bytes(body)
                _atomic_write_bytes(body_path, body)
                _atomic_write_json(
                    metadata_path,
                    {
                        "url": url,
                        "final_url": final_url,
                        "retrieved_at": retrieved_at,
                        "sha256": digest,
                        "status": status,
                    },
                )
                return FetchResult(
                    url,
                    final_url,
                    body,
                    digest,
                    retrieved_at,
                    False,
                )
            retryable = status == 0 or status == 429 or 500 <= status <= 599
            if not retryable:
                raise FetchError(f"HTTP {status} for {url}")
            if attempt >= self.max_retries:
                break
            delay = self._retry_after(response_headers)
            if delay is None:
                delay = min(60.0, 2.0**attempt)
            self._sleep(delay)
        detail = f": {last_error}" if last_error else ""
        raise FetchError(
            f"request failed after {self.max_retries + 1} attempts: {url}{detail}"
        )

    def fetch_svelte(
        self,
        url: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[Any], FetchResult]:
        result = self.fetch(url, force_refresh=force_refresh)
        return decode_svelte_data(result.body), result


def ensure_robots_allowed(client: HttpCacheClient, urls: Iterable[str]) -> None:
    result = client.fetch(ROBOTS_URL)
    try:
        lines = result.body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise FetchError("robots.txt is not UTF-8") from error
    policy = urllib.robotparser.RobotFileParser()
    policy.set_url(ROBOTS_URL)
    policy.parse(lines)
    for url in urls:
        if not policy.can_fetch(client.user_agent, url):
            raise RobotsDeniedError(f"robots policy disallows {url}")
    crawl_delay = policy.crawl_delay(client.user_agent)
    if crawl_delay is None:
        crawl_delay = policy.crawl_delay("*")
    if crawl_delay is not None:
        client.min_interval_seconds = max(
            client.min_interval_seconds,
            float(crawl_delay),
        )


def _question_previews(decoded_nodes: Iterable[Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for node in decoded_nodes:
        for item in _walk(node):
            question_id = item.get("question_id")
            if (
                isinstance(question_id, str)
                and QUESTION_ID_RE.fullmatch(question_id)
                and "content" in item
                and "question" not in item
                and question_id not in seen
            ):
                seen.add(question_id)
                ids.append(question_id)
    return ids


def _full_questions(
    decoded_nodes: Iterable[Any],
    *,
    paper_slug: str,
) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for node in decoded_nodes:
        for item in _walk(node):
            question_id = item.get("question_id")
            if (
                isinstance(question_id, str)
                and QUESTION_ID_RE.fullmatch(question_id)
                and isinstance(item.get("question"), dict)
                and item.get("paperId") == paper_slug
            ):
                questions[question_id] = item
    return questions


def _optional_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _booklet_code(question: Mapping[str, Any]) -> str | None:
    for key in (
        "booklet_code",
        "bookletCode",
        "paper_code",
        "paperCode",
        "booklet",
    ):
        value = question.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return str(value)
    return None


def sanitize_question(
    question: Mapping[str, Any],
    *,
    paper: PaperReference,
    discovery_result: FetchResult,
    question_result: FetchResult,
    retrieved_via_data_url: str,
) -> dict[str, Any]:
    """Create an allowlisted record that cannot contain explanation text."""

    question_id = question.get("question_id")
    if not isinstance(question_id, str) or not QUESTION_ID_RE.fullmatch(question_id):
        raise ExamSideIndexError("full question is missing a safe question_id")
    languages = question.get("question")
    if not isinstance(languages, dict) or not languages:
        raise ExamSideIndexError(f"question {question_id} has no language payload")
    language = "en" if isinstance(languages.get("en"), dict) else next(
        (key for key, value in languages.items() if isinstance(value, dict)),
        None,
    )
    if language is None:
        raise ExamSideIndexError(f"question {question_id} has no usable language")
    localized = languages[language]
    content = localized.get("content")
    if not isinstance(content, str):
        raise ExamSideIndexError(f"question {question_id} has no text content")

    sanitized_options: list[dict[str, str]] = []
    options = localized.get("options")
    if options is not None:
        if not isinstance(options, list):
            raise ExamSideIndexError(f"question {question_id} options are malformed")
        for option in options:
            if not isinstance(option, dict):
                raise ExamSideIndexError(f"question {question_id} option is malformed")
            identifier = option.get("identifier")
            option_content = option.get("content")
            if not isinstance(identifier, str) or not isinstance(option_content, str):
                raise ExamSideIndexError(f"question {question_id} option is incomplete")
            sanitized_options.append(
                {"identifier": identifier, "content": option_content}
            )

    correct_options = localized.get("correct_options")
    if correct_options is None:
        sanitized_correct_options: list[str] = []
    elif isinstance(correct_options, list) and all(
        isinstance(option, str) for option in correct_options
    ):
        sanitized_correct_options = list(correct_options)
    else:
        raise ExamSideIndexError(f"question {question_id} correct options are malformed")

    explanation = localized.get("explanation")
    has_explanation = explanation not in (None, "", [], {})
    explanation_sha256 = _sha256_value(explanation) if has_explanation else None
    canonical_question_url = f"{paper.url}/{question_id}"
    canonical_data_url = f"{canonical_question_url}/__data.json"

    return {
        "schema_version": SCHEMA_VERSION,
        "source_site": SOURCE_SITE,
        "source_role": SOURCE_ROLE,
        "is_authoritative": False,
        "materialization_allowed": False,
        "verification_notice": (
            "Secondary reconciliation reference only; verify against an official "
            "paper and final answer key before archive use."
        ),
        "paper": {
            "slug": paper.slug,
            "source_id": paper.source_id,
            "title": paper.title,
            "year": paper.year,
            "session": paper.session,
            "url": paper.url,
            "data_url": paper.data_url,
            "booklet_policy": paper.booklet_policy,
        },
        "question": {
            "source_id": question_id,
            "language": language,
            "url": canonical_question_url,
            "data_url": canonical_data_url,
            "permalink": _optional_scalar(question.get("permalink")),
            "question_text": content,
            "direction_text": _optional_scalar(localized.get("direction")),
            "comprehension_text": _optional_scalar(localized.get("comprehension")),
            "options": sanitized_options,
            "correct_options": sanitized_correct_options,
            "numerical_answer": _optional_scalar(localized.get("answer")),
            "question_type": _optional_scalar(question.get("type")),
            "marks": _optional_scalar(question.get("marks")),
            "negative_marks": _optional_scalar(question.get("negMarks")),
            "subject": _optional_scalar(question.get("subject")),
            "chapter": _optional_scalar(question.get("chapter")),
            "chapter_group": _optional_scalar(question.get("chapterGroup")),
            "topic": _optional_scalar(question.get("topic")),
            "booklet_code": _booklet_code(question),
            "is_out_of_syllabus": _optional_scalar(question.get("isOutOfSyllabus")),
            "is_bonus": _optional_scalar(question.get("isBonus")),
            "has_explanation": has_explanation,
            "explanation_sha256": explanation_sha256,
        },
        "provenance": {
            "paper_discovery_url": YEAR_INDEX_URL,
            "paper_discovery_data_url": YEAR_INDEX_DATA_URL,
            "paper_discovery_raw_sha256": discovery_result.sha256,
            "retrieved_via_data_url": retrieved_via_data_url,
            "question_raw_sha256": question_result.sha256,
            "retrieved_at": question_result.retrieved_at,
            "raw_cache_is_ignored": True,
        },
    }


def _load_jsonl(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return records
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            if line_number == len(lines):
                # A process can stop between write() and the terminating newline.
                # The valid prefix remains resumable and is compacted before append.
                break
            raise ExamSideIndexError(
                f"invalid JSONL at {path}:{line_number}"
            ) from error
        if record.get("source_role") != SOURCE_ROLE:
            raise ExamSideIndexError(f"unexpected record role at {path}:{line_number}")
        paper_slug = record.get("paper", {}).get("slug")
        question_id = record.get("question", {}).get("source_id")
        if not isinstance(paper_slug, str) or not isinstance(question_id, str):
            raise ExamSideIndexError(f"invalid record key at {path}:{line_number}")
        records[(paper_slug, question_id)] = record
    return records


def _rewrite_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    body = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    _atomic_write_bytes(path, body)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "source_role": SOURCE_ROLE,
            "question_sources": {},
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("source_role") != SOURCE_ROLE:
        raise ExamSideIndexError("crawl state belongs to a different source role")
    if not isinstance(value.get("question_sources"), dict):
        raise ExamSideIndexError("crawl state question_sources is malformed")
    return value


@dataclass(frozen=True)
class CrawlSummary:
    discovered_papers: int
    selected_papers: int
    existing_records: int
    added_records: int
    total_records: int
    output_path: Path


class ExamSideReferenceCrawler:
    """Orchestrate discovery and sanitized, resumable question indexing."""

    def __init__(
        self,
        work_dir: Path = DEFAULT_WORK_DIR,
        *,
        client: HttpCacheClient | None = None,
    ) -> None:
        self.work_dir = work_dir
        self.raw_dir = work_dir / "raw"
        self.output_path = work_dir / "examside_reference_index.jsonl"
        self.state_path = work_dir / "crawl_state.json"
        self.client = client or HttpCacheClient(self.raw_dir)

    def discover(
        self,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[PaperReference], FetchResult]:
        ensure_robots_allowed(self.client, [YEAR_INDEX_URL, YEAR_INDEX_DATA_URL])
        decoded, result = self.client.fetch_svelte(
            YEAR_INDEX_DATA_URL,
            force_refresh=force_refresh,
        )
        return discover_papers(decoded), result

    def run(
        self,
        *,
        paper_slugs: Iterable[str] = (),
        all_papers: bool = False,
        max_questions: int | None = None,
        force_refresh: bool = False,
    ) -> CrawlSummary:
        if max_questions is not None and max_questions < 1:
            raise ValueError("max_questions must be positive")
        requested = tuple(dict.fromkeys(paper_slugs))
        if all_papers and requested:
            raise ValueError("choose explicit paper slugs or all_papers, not both")

        self.work_dir.mkdir(parents=True, exist_ok=True)
        papers, discovery_result = self.discover(force_refresh=force_refresh)
        by_slug = {paper.slug: paper for paper in papers}
        unknown = [slug for slug in requested if slug not in by_slug]
        if unknown:
            raise DiscoveryError(f"unknown or out-of-scope paper slug(s): {unknown}")
        selected = papers if all_papers else [by_slug[slug] for slug in requested]

        existing = _load_jsonl(self.output_path)
        # Compact a partial final line and make deduplication deterministic.
        _rewrite_jsonl(self.output_path, existing.values())
        initial_count = len(existing)
        state = _load_state(self.state_path)
        state.update(
            {
                "schema_version": SCHEMA_VERSION,
                "source_role": SOURCE_ROLE,
                "discovered_paper_count": len(papers),
                "updated_at": _utc_now(),
            }
        )
        _atomic_write_json(self.state_path, state)

        added = 0
        for paper in selected:
            if max_questions is not None and added >= max_questions:
                break
            ensure_robots_allowed(self.client, [paper.url, paper.data_url])
            paper_nodes, _paper_result = self.client.fetch_svelte(
                paper.data_url,
                force_refresh=force_refresh,
            )
            question_ids = _question_previews(paper_nodes)
            if not question_ids:
                raise ExamSideIndexError(f"no public question IDs found for {paper.slug}")

            paper_sources = state["question_sources"].setdefault(paper.slug, {})
            if not isinstance(paper_sources, dict):
                raise ExamSideIndexError(f"invalid saved source map for {paper.slug}")
            in_memory: dict[
                str,
                tuple[dict[str, Any], FetchResult, str],
            ] = {}

            for question_id in question_ids:
                if max_questions is not None and added >= max_questions:
                    break
                key = (paper.slug, question_id)
                if key in existing:
                    continue
                data_url = paper_sources.get(question_id)
                if not isinstance(data_url, str):
                    data_url = f"{paper.url}/{question_id}/__data.json"

                if question_id not in in_memory:
                    ensure_robots_allowed(self.client, [data_url])
                    question_nodes, question_result = self.client.fetch_svelte(
                        data_url,
                        force_refresh=force_refresh,
                    )
                    extracted = _full_questions(
                        question_nodes,
                        paper_slug=paper.slug,
                    )
                    if question_id not in extracted:
                        raise ExamSideIndexError(
                            f"question endpoint did not contain {paper.slug}/{question_id}"
                        )
                    for extracted_id, full_question in extracted.items():
                        if extracted_id in question_ids:
                            in_memory[extracted_id] = (
                                full_question,
                                question_result,
                                data_url,
                            )
                            paper_sources[extracted_id] = data_url
                    state["updated_at"] = _utc_now()
                    _atomic_write_json(self.state_path, state)

                full_question, question_result, fetched_data_url = in_memory[question_id]
                record = sanitize_question(
                    full_question,
                    paper=paper,
                    discovery_result=discovery_result,
                    question_result=question_result,
                    retrieved_via_data_url=fetched_data_url,
                )
                existing[key] = record
                with self.output_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                added += 1

        state["record_count"] = len(existing)
        state["updated_at"] = _utc_now()
        _atomic_write_json(self.state_path, state)
        return CrawlSummary(
            discovered_papers=len(papers),
            selected_papers=len(selected),
            existing_records=initial_count,
            added_records=added,
            total_records=len(existing),
            output_path=self.output_path,
        )


def _runtime_path(value: Path) -> Path:
    resolved = value.resolve()
    try:
        resolved.relative_to(RUNTIME_ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"runtime output must stay below ignored directory {RUNTIME_ROOT}"
        ) from error
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Ignored runtime/cache directory below repository tmp/.",
    )
    parser.add_argument(
        "--paper",
        action="append",
        default=[],
        help="Crawl one audited paper slug (repeatable). Without this, discovery only.",
    )
    parser.add_argument(
        "--all-papers",
        action="store_true",
        help="Explicitly crawl all 39 independent papers.",
    )
    parser.add_argument("--max-questions", type=int)
    parser.add_argument("--delay-seconds", type=float, default=1.5)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args(argv)
    if args.all_papers and args.paper:
        parser.error("--paper and --all-papers are mutually exclusive")
    if args.max_questions is not None and args.max_questions < 1:
        parser.error("--max-questions must be positive")
    try:
        args.work_dir = _runtime_path(args.work_dir)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = HttpCacheClient(
        args.work_dir / "raw",
        user_agent=args.user_agent,
        min_interval_seconds=args.delay_seconds,
        max_retries=args.max_retries,
        timeout_seconds=args.timeout_seconds,
    )
    crawler = ExamSideReferenceCrawler(args.work_dir, client=client)
    summary = crawler.run(
        paper_slugs=args.paper,
        all_papers=args.all_papers,
        max_questions=args.max_questions,
        force_refresh=args.force_refresh,
    )
    if not args.paper and not args.all_papers:
        print(
            f"Discovered {summary.discovered_papers} independent GATE CSE papers "
            f"for {YEAR_MIN}-{YEAR_MAX}; discovery-only mode wrote no questions."
        )
    else:
        print(
            f"Discovered {summary.discovered_papers} papers; selected "
            f"{summary.selected_papers}; added {summary.added_records} sanitized "
            f"records ({summary.total_records} total) at {summary.output_path}."
        )
    print(
        "Reference only: no record is authoritative or eligible for materialization.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
