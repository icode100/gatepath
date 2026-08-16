from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "index_examside_reference.py"
)
SPEC = importlib.util.spec_from_file_location(
    "index_examside_reference",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _flatten(value: Any) -> list[Any]:
    """Small fixture encoder for the ordinary devalue subset used in tests."""

    flattened: list[Any] = []

    def add(child: Any) -> int:
        index = len(flattened)
        flattened.append(None)
        if isinstance(child, dict):
            flattened[index] = {key: add(item) for key, item in child.items()}
        elif isinstance(child, list):
            flattened[index] = [add(item) for item in child]
        else:
            flattened[index] = child
        return index

    assert add(value) == 0
    return flattened


def _svelte_payload(value: Any) -> bytes:
    return json.dumps(
        {"type": "data", "nodes": [{"type": "data", "data": _flatten(value)}]},
        separators=(",", ":"),
    ).encode("utf-8")


def _paper_inventory_root() -> dict[str, Any]:
    papers: list[dict[str, Any]] = []
    for ordinal, slug in enumerate(MODULE.expected_paper_slugs(), start=1):
        match = MODULE.PAPER_SLUG_RE.fullmatch(slug)
        assert match is not None
        year = int(match.group("year"))
        papers.append(
            {
                "key": slug,
                "metaId": f"paper-id-{ordinal}",
                "title": slug.replace("-", " ").upper(),
                "year": year,
            }
        )
    # These are deliberately not independent paper/session slugs. In
    # particular, a 2013 booklet label must not become another paper.
    papers.append({"key": "gate-cse-2013-booklet-a", "year": 2013})
    papers.append({"key": "gate-cse-2026-set-1", "year": 2026})
    return {"papers": papers}


def _full_question(
    question_id: str,
    *,
    explanation: str,
    content: str = "<p>Find $x$.</p>",
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "paperId": "gate-cse-2025-set-2",
        "paperTitle": "GATE CSE 2025 Set 2",
        "permalink": f"public-{question_id}",
        "subject": "computer-networks",
        "chapter": "transport-layer",
        "chapterGroup": None,
        "topic": "tcp",
        "type": "mcq",
        "marks": 1,
        "negMarks": 0.33,
        "isOutOfSyllabus": False,
        "isBonus": False,
        "question": {
            "en": {
                "content": content,
                "direction": None,
                "comprehension": None,
                "options": [
                    {"identifier": "A", "content": "<p>$1$</p>"},
                    {"identifier": "B", "content": "<img src=\"https://cdn.example/b.png\">"},
                ],
                "correct_options": ["B"],
                "answer": None,
                "explanation": explanation,
            }
        },
    }


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Transport:
    def __init__(
        self,
        responses: Mapping[
            str,
            tuple[int, Mapping[str, str], bytes, str]
            | list[tuple[int, Mapping[str, str], bytes, str]],
        ],
    ) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes, str]:
        self.calls.append((url, dict(headers)))
        response = self.responses[url]
        if isinstance(response, list):
            return response.pop(0)
        return response


def test_safe_devalue_decoder_decodes_references_without_eval() -> None:
    payload = _svelte_payload(
        {
            "message": "safe",
            "items": [42, {"nested": True}],
            "empty": None,
        }
    )

    assert MODULE.decode_svelte_data(payload) == [
        {
            "message": "safe",
            "items": [42, {"nested": True}],
            "empty": None,
        }
    ]


def test_safe_devalue_decoder_uses_official_negative_sentinels() -> None:
    decoder = MODULE._SafeDevalueDecoder(
        [
            {
                "undefined": -1,
                "hole": -2,
                "nan": -3,
                "positive_infinity": -4,
                "negative_infinity": -5,
                "negative_zero": -6,
                "sparse": 1,
            },
            [-7, 4, 1, 2, 3, 3],
            "one",
            "three",
        ]
    )

    decoded = decoder.decode()
    assert decoded["undefined"] is None
    assert decoded["hole"] is None
    assert MODULE.math.isnan(decoded["nan"])
    assert decoded["positive_infinity"] == MODULE.math.inf
    assert decoded["negative_infinity"] == -MODULE.math.inf
    assert MODULE.math.copysign(1.0, decoded["negative_zero"]) == -1.0
    assert decoded["sparse"] == [None, "one", None, "three"]


@pytest.mark.parametrize(
    "flattened,match",
    [
        ([[-7]], "integer length"),
        ([[-7, 2, 2, 1], "value"], "outside"),
        ([[-7, 2, 1]], "incomplete"),
        ([[-7, 2, 1, 1, 1, 2], "a", "b"], "repeated"),
    ],
)
def test_safe_devalue_decoder_rejects_malformed_sparse_arrays(
    flattened: list[Any],
    match: str,
) -> None:
    payload = {
        "type": "data",
        "nodes": [{"type": "data", "data": flattened}],
    }

    with pytest.raises(MODULE.DevalueDecodeError, match=match):
        MODULE.decode_svelte_data(payload)


@pytest.mark.parametrize(
    "flattened,match",
    [
        ([{"value": 99}], "outside"),
        ([{"self": 0}], "cyclic"),
        ([{"__proto__": 1}, "polluted"], "blocked"),
        ([["Function", 1], "alert(1)"], "unsupported devalue tag"),
    ],
)
def test_safe_devalue_decoder_rejects_unsafe_or_malformed_graphs(
    flattened: list[Any],
    match: str,
) -> None:
    payload = {
        "type": "data",
        "nodes": [{"type": "data", "data": flattened}],
    }

    with pytest.raises(MODULE.DevalueDecodeError, match=match):
        MODULE.decode_svelte_data(payload)


def test_discovery_finds_39_independent_papers_and_keeps_2013_single() -> None:
    papers = MODULE.discover_papers([_paper_inventory_root()])

    assert len(papers) == 39
    assert {paper.year for paper in papers} == set(range(1996, 2026))
    paper_2013 = [paper for paper in papers if paper.year == 2013]
    assert [paper.slug for paper in paper_2013] == ["gate-cse-2013"]
    assert paper_2013[0].session == "main"
    assert (
        paper_2013[0].booklet_policy
        == "single_independent_paper_preserve_question_booklet_codes"
    )


def test_http_client_rate_limits_retries_and_resumes_from_verified_cache(
    tmp_path: Path,
) -> None:
    url = MODULE.YEAR_INDEX_DATA_URL
    body = _svelte_payload({"ok": True})
    transport = _Transport(
        {
            url: [
                (503, {"Retry-After": "0.25"}, b"busy", url),
                (200, {"Content-Type": "application/json"}, body, url),
            ]
        }
    )
    clock = _FakeClock()
    client = MODULE.HttpCacheClient(
        tmp_path / "raw",
        min_interval_seconds=0.5,
        max_retries=1,
        transport=transport,
        sleep=clock.sleep,
        clock=clock.clock,
    )

    first = client.fetch(url)
    second = client.fetch(url)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.sha256 == hashlib.sha256(body).hexdigest()
    assert len(transport.calls) == 2
    assert sum(clock.sleeps) >= 0.5
    assert all("GatePath-Reconciliation-Indexer" in call[1]["User-Agent"] for call in transport.calls)


def test_crawler_pilot_sanitizes_explanations_and_is_idempotently_resumable(
    tmp_path: Path,
) -> None:
    paper_slug = "gate-cse-2025-set-2"
    paper_url = f"{MODULE.YEAR_INDEX_URL}/{paper_slug}"
    paper_data_url = f"{paper_url}/__data.json"
    q1_data_url = f"{paper_url}/q-one/__data.json"
    explanation_secret = "THIRD PARTY EXPLANATION MUST NOT ENTER JSONL"
    index_body = _svelte_payload(_paper_inventory_root())
    paper_body = _svelte_payload(
        {
            "questions": [
                {"question_id": "q-one", "content": "preview one"},
                {"question_id": "q-two", "content": "preview two"},
            ]
        }
    )
    question_body = _svelte_payload(
        {
            "questions": [
                _full_question(
                    "q-one",
                    explanation=explanation_secret,
                    content="<p>Question with $\\LaTeX$.</p>",
                ),
                _full_question("q-two", explanation="second explanation"),
            ]
        }
    )
    robots = b"User-agent: *\nAllow: /\n"
    responses = {
        MODULE.ROBOTS_URL: (200, {"Content-Type": "text/plain"}, robots, MODULE.ROBOTS_URL),
        MODULE.YEAR_INDEX_DATA_URL: (
            200,
            {"Content-Type": "application/json"},
            index_body,
            MODULE.YEAR_INDEX_DATA_URL,
        ),
        paper_data_url: (
            200,
            {"Content-Type": "application/json"},
            paper_body,
            paper_data_url,
        ),
        q1_data_url: (
            200,
            {"Content-Type": "application/json"},
            question_body,
            q1_data_url,
        ),
    }
    transport = _Transport(responses)
    work_dir = tmp_path / "examside"
    client = MODULE.HttpCacheClient(
        work_dir / "raw",
        min_interval_seconds=0,
        transport=transport,
    )
    crawler = MODULE.ExamSideReferenceCrawler(work_dir, client=client)

    first = crawler.run(paper_slugs=[paper_slug], max_questions=2)
    raw_output = crawler.output_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw_output.splitlines()]

    assert first.discovered_papers == 39
    assert first.added_records == 2
    assert first.total_records == 2
    assert explanation_secret not in raw_output
    assert all(row["source_role"] == MODULE.SOURCE_ROLE for row in rows)
    assert all(row["is_authoritative"] is False for row in rows)
    assert all(row["materialization_allowed"] is False for row in rows)
    first_question = rows[0]["question"]
    assert first_question["question_text"] == "<p>Question with $\\LaTeX$.</p>"
    assert first_question["options"][1] == {
        "identifier": "B",
        "content": "<img src=\"https://cdn.example/b.png\">",
    }
    assert first_question["correct_options"] == ["B"]
    assert first_question["has_explanation"] is True
    assert first_question["explanation_sha256"] == hashlib.sha256(
        explanation_secret.encode("utf-8")
    ).hexdigest()
    assert "explanation" not in first_question
    assert rows[0]["provenance"]["retrieved_via_data_url"] == q1_data_url
    assert len(list((work_dir / "raw").glob("*.json"))) > 0

    def fail_transport(
        _url: str,
        _headers: Mapping[str, str],
        _timeout: float,
        _max_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes, str]:
        raise AssertionError("resume should use the raw cache")

    resumed_client = MODULE.HttpCacheClient(
        work_dir / "raw",
        min_interval_seconds=0,
        transport=fail_transport,
    )
    resumed = MODULE.ExamSideReferenceCrawler(
        work_dir,
        client=resumed_client,
    ).run(paper_slugs=[paper_slug], max_questions=2)

    assert resumed.added_records == 0
    assert resumed.total_records == 2
    assert len(crawler.output_path.read_text(encoding="utf-8").splitlines()) == 2


def test_default_cli_is_discovery_only_and_runtime_output_is_ignored_tmp() -> None:
    args = MODULE.parse_args([])

    assert args.paper == []
    assert args.all_papers is False
    assert args.work_dir.is_relative_to(MODULE.RUNTIME_ROOT.resolve())
