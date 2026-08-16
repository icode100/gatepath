from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "index_pyq_answer_keys.py"
MANIFEST_PATH = BACKEND_DIR / "data" / "pyq_source_manifest.json"
SPEC = importlib.util.spec_from_file_location("index_pyq_answer_keys", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def built() -> tuple[dict, dict]:
    return MODULE.build_index(MANIFEST_PATH)


def _paper(manifest: dict, paper_id: str) -> dict:
    return next(paper for paper in manifest["papers"] if paper["id"] == paper_id)


def _claim(
    artifact: dict,
    paper_id: str,
    ordinal: int,
    *,
    role: str = "answer_key",
) -> dict:
    return next(
        claim
        for claim in artifact["claims"]
        if claim["source_paper_id"] == paper_id
        and claim["canonical_ordinal"] == ordinal
        and claim["source_role"] == role
    )


def _resolution(artifact: dict, paper_id: str, ordinal: int) -> dict:
    return next(
        row
        for row in artifact["resolutions"]
        if row["source_paper_id"] == paper_id
        and row["canonical_ordinal"] == ordinal
    )


def test_manifest_source_identity_and_correct_session_attachment() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = {
        "gate-cs-2012": ("ca6398bb9c8f83dfa0dc5d768030a42ec45e8d450e2afe9f1b55728c5e873f9d", 53546, 2),
        "gate-cs-2013": ("8dec600fbeb2c78b0f9af489cea3a130b1976d3f0d5ed793743f4dbdd237747d", 8396, 2),
        "gate-cs-2014-session-1": ("4ee56f8fb5d896efed15be67a53ce82841ba7f7663d4d1ae3cd432b13369cbfe", 73802, 1),
        "gate-cs-2014-session-2": ("2672e2cd276d7e4390370f9c11d2d2bb3f110e84309c3666eb8a7a2b9d208f65", 73836, 1),
        "gate-cs-2014-session-3": ("c617e89afa211da79d08c8f468029311e0d72feb3c8c237223e8b2f05e1c2446", 73542, 1),
        "gate-cs-2015-session-1": ("201a7d66929a121f8d89d6277cf3774e1118dbf9dd48b8e99c7099ad37861e6c", 6477331, 24),
        "gate-cs-2015-session-2": ("99687d6b2679e106f747df67ce2cb728242f5ff655cadcc5c652947417612171", 6772907, 25),
        "gate-cs-2015-session-3": ("e08dedac660110701c4af7b6477a723ac334b6184dd101719e571de11f5ed722", 6998312, 27),
        "gate-cs-2016-session-1": ("f03004d37893d97530a4607d2880fdb3c8d8f6dca6f86a16a204db1d34e59058", 138154, 2),
        "gate-cs-2016-session-2": ("8a7d72fe5ec2bee31a39e437a915c71f6b681765795708d8c063f73924565a86", 138133, 2),
        "gate-cs-2017-session-2": ("5853f7ade0bff6021a359c23ae9f74c6d37bf90c0d366be68e0a651d80b93aa1", 54720, 2),
        "gate-cs-2018": ("ff3548830a2aff781f0eaedeea514e1df7fd983270f0d0d7edf1c30b22302ca5", 61695, 3),
        "gate-cs-2019": ("a1b31dced13cca46698776248f07acaa95efa3f27e568e124cd10faad391d3d9", 59766, 3),
        "gate-cs-2020": ("32e8ef289489183df1cde37d4b5f73963386dfa00af2691d5309c1d464c4c583", 246090, 1),
        "gate-cs-2021-session-1": ("856c52ae348b6b0583fdb1ee3d7664e9d5752bc50068ca6b33d334b2c453edd4", 1196112, 6),
        "gate-cs-2022": ("ee00149bd2d2ddc1b7489113ba1e7db72317ca77e8ca5b438f4dd852016457b4", 429929, 2),
        "gate-cs-2023": ("80fae0c7c43c6ee3c8b467e2187a1ff3d2984b377aa03940b0d143867a18dc60", 103586, 2),
        "gate-cs-2024-set-1": ("f713276ef5a4cc59d6c5925ba7e4c72f6f669ab6866956cc45cb8f3e0f5817cf", 313008, 2),
        "gate-cs-2024-set-2": ("04ccb9fdda662d4c6674451525c73c5f599fce05ce6010f752a0803b5dad6948", 313035, 2),
    }
    for paper_id, identity in expected.items():
        paper = _paper(manifest, paper_id)
        assert (
            paper["answer_key_local_sha256"],
            paper["answer_key_local_bytes"],
            paper["answer_key_local_page_count"],
        ) == identity
        assert paper["answer_key_authority"].startswith("primary_official")

    assert _paper(manifest, "gate-cs-2015-session-1")["answer_key_url"].endswith("CS_S05.pdf")
    assert _paper(manifest, "gate-cs-2015-session-2")["answer_key_url"].endswith("CS_S06.pdf")
    assert _paper(manifest, "gate-cs-2015-session-3")["answer_key_url"].endswith("CS_S07.pdf")


def test_exhaustive_counts_ranges_duplicates_and_staging_guards(built: tuple[dict, dict]) -> None:
    artifact, report = built
    assert artifact["production_import_authorized"] is False
    assert artifact["practice_promotion_authorized"] is False
    assert report["production_import_authorized"] is False
    assert report["practice_promotion_authorized"] is False
    assert artifact["summary"] == {
        "paper_count": 39,
        "manifest_file_declaration_count": 64,
        "manifest_unique_file_count": 58,
        "answer_source_count": 40,
        "parsed_source_count": 35,
        "manual_gap_source_count": 5,
        "claim_count": 2300,
        "official_claim_count": 1625,
        "secondary_claim_count": 675,
        "official_resolution_count": 1560,
        "secondary_two_source_resolution_count": 0,
        "secondary_unverified_count": 90,
        "conflict_count": 2,
        "gap_count": 1062,
        "claims_by_paper": artifact["summary"]["claims_by_paper"],
        "official_resolutions_by_paper": artifact["summary"]["official_resolutions_by_paper"],
    }
    # Corrected pre-acquisition baseline was 44 declarations / 39 unique files.
    assert 64 - 44 == 20
    assert 58 - 39 == 19

    by_source: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for claim in artifact["claims"]:
        by_source[(claim["source_paper_id"], claim["source_role"], claim["source_sha256"])].append(
            claim["canonical_ordinal"]
        )
    for source in artifact["sources"]:
        key = (source["source_paper_id"], source["role"], source["sha256"])
        ordinals = by_source[key]
        assert len(ordinals) == len(set(ordinals))
        if source["authority_level"] == "official":
            assert sorted(ordinals) == list(range(1, 66))

    assert len({claim["claim_id"] for claim in artifact["claims"]}) == 2300
    assert not any(conflict["kind"] == "official_claim_conflict" for conflict in artifact["conflicts"])


def test_2017_technical_first_numbering_is_mapped_for_both_sessions(built: tuple[dict, dict]) -> None:
    artifact, _ = built
    for paper_id in ("gate-cs-2017-session-1", "gate-cs-2017-session-2"):
        source_first = next(
            claim for claim in artifact["claims"]
            if claim["source_paper_id"] == paper_id
            and claim["source_role"] == "answer_key"
            and claim["source_question_number"] == 1
        )
        source_56 = next(
            claim for claim in artifact["claims"]
            if claim["source_paper_id"] == paper_id
            and claim["source_role"] == "answer_key"
            and claim["source_question_number"] == 56
        )
        assert (source_first["section"], source_first["canonical_ordinal"], source_first["item_label"]) == ("CS", 11, "CS-1")
        assert (source_56["section"], source_56["canonical_ordinal"], source_56["item_label"]) == ("GA", 1, "GA-1")


def test_2013_key_is_joined_through_all_four_verified_booklets(
    built: tuple[dict, dict],
) -> None:
    artifact, report = built
    claims = [
        claim
        for claim in artifact["claims"]
        if claim["source_paper_id"] == "gate-cs-2013"
    ]
    assert len(claims) == 65
    assert sorted(claim["canonical_ordinal"] for claim in claims) == list(range(1, 66))
    assert Counter(claim["marks"] for claim in claims) == {1: 30, 2: 35}
    assert {_claim(artifact, "gate-cs-2013", 1)["raw_key"]} == {"A"}
    assert {_claim(artifact, "gate-cs-2013", 65)["raw_key"]} == {"B"}
    assert (
        _claim(artifact, "gate-cs-2013", 1)["key_page"],
        _claim(artifact, "gate-cs-2013", 65)["key_page"],
    ) == (1, 2)
    assert {
        claim["canonical_ordinal"]
        for claim in claims
        if claim["answer"]["kind"] == "marks_to_all"
    } == {42, 47}
    assert {
        flag
        for claim in claims
        for flag in claim["review_flags"]
    } == {"verified_against_all_260_booklet_occurrences_exact_sha"}
    assert all(
        _resolution(artifact, "gate-cs-2013", ordinal)["status"] == "official"
        for ordinal in range(1, 66)
    )
    assert "gate-cs-2013" not in report["paper_gaps"]


def test_2013_booklet_map_rejects_duplicate_occurrence_even_when_keys_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources, _ = MODULE._manifest_sources(manifest, MANIFEST_PATH)
    source = next(
        item
        for item in sources
        if item.paper_id == "gate-cs-2013" and item.role == "answer_key"
    )
    parsed = MODULE._verified_2013_booklet_rows(source)
    ordinals_by_key: dict[str, list[int]] = defaultdict(list)
    for row in parsed:
        ordinals_by_key[row.raw_key].append(row.source_question_number)
    first, second = next(
        ordinals[:2]
        for ordinals in ordinals_by_key.values()
        if len(ordinals) >= 2
    )

    mapping = json.loads(
        MODULE.DEFAULT_2013_BOOKLET_MAP.read_text(encoding="utf-8")
    )
    items = {
        int(item["canonical_ordinal"]): item for item in mapping["items"]
    }
    duplicate = next(
        dict(occurrence)
        for occurrence in items[first]["occurrences"]
        if occurrence["booklet_code"] == "B"
    )
    items[second]["occurrences"] = [
        duplicate if occurrence["booklet_code"] == "B" else occurrence
        for occurrence in items[second]["occurrences"]
    ]
    tampered = tmp_path / "gate_cs_2013_booklet_occurrences.json"
    tampered.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setattr(MODULE, "DEFAULT_2013_BOOKLET_MAP", tampered)

    with pytest.raises(MODULE.AnswerKeyIndexError, match="duplicate code-B occurrence"):
        MODULE._verified_2013_booklet_rows(source)


def test_2015_visual_keys_have_exact_endpoints_types_marks_and_pages(built: tuple[dict, dict]) -> None:
    artifact, _ = built
    expected = {
        "gate-cs-2015-session-1": ("A", "B", 1, 23),
        "gate-cs-2015-session-2": ("C", "19.2", 1, 24),
        "gate-cs-2015-session-3": ("B", "D", 1, 26),
    }
    for paper_id, (first, last, first_page, last_page) in expected.items():
        claims = [
            claim for claim in artifact["claims"]
            if claim["source_paper_id"] == paper_id and claim["source_role"] == "answer_key"
        ]
        assert len(claims) == 65
        q1, q65 = _claim(artifact, paper_id, 1), _claim(artifact, paper_id, 65)
        assert q1["raw_key"] == first
        assert q65["raw_key"].split(" to ")[0] == last
        assert (q1["key_page"], q65["key_page"]) == (first_page, last_page)
        assert Counter(claim["marks"] for claim in claims) == {1: 30, 2: 35}


def test_2021_merged_key_crosschecks_session_2_exactly(built: tuple[dict, dict]) -> None:
    artifact, _ = built
    for ordinal in range(1, 66):
        official = [
            claim for claim in artifact["claims"]
            if claim["source_paper_id"] == "gate-cs-2021-session-2"
            and claim["canonical_ordinal"] == ordinal
            and claim["source_authority_level"] == "official"
        ]
        assert len(official) == 2
        assert len({MODULE._fingerprint(claim) for claim in official}) == 1


def test_2025_full_keys_and_examside_missing_nat_ranges_are_resolved(built: tuple[dict, dict]) -> None:
    artifact, _ = built
    expected_distributions = {
        "gate-cs-2025-set-1": {"MCQ": 30, "MSQ": 13, "NAT": 22},
        "gate-cs-2025-set-2": {"MCQ": 32, "MSQ": 18, "NAT": 15},
    }
    for paper_id, expected in expected_distributions.items():
        claims = [
            claim for claim in artifact["claims"]
            if claim["source_paper_id"] == paper_id and claim["source_role"] == "answer_key"
        ]
        assert len(claims) == 65
        assert Counter(claim["question_type"] for claim in claims) == expected
        assert sorted(claim["canonical_ordinal"] for claim in claims) == list(range(1, 66))

    expected_ranges = {
        52: [("6", "6")],
        53: [("11.83", "11.87")],
        57: [("7", "7")],
        64: [("5", "5")],
    }
    for ordinal, ranges in expected_ranges.items():
        claim = _claim(artifact, "gate-cs-2025-set-1", ordinal)
        assert claim["question_type"] == "NAT"
        assert claim["key_page"] == 2
        assert [
            (item["minimum"], item["maximum"])
            for item in claim["answer"]["ranges"]
        ] == ranges
        assert _resolution(artifact, "gate-cs-2025-set-1", ordinal)["status"] == "official"


def test_community_only_answers_stay_unverified(built: tuple[dict, dict]) -> None:
    artifact, report = built
    legacy_2004 = [
        row for row in artifact["resolutions"] if row["source_paper_id"] == "gate-cs-2004"
    ]
    assert len(legacy_2004) == 90
    assert {row["status"] for row in legacy_2004} == {"secondary_single_source_unverified"}
    assert all(row["selected_answer"] is None for row in legacy_2004)

    assert not [
        gap for gap in artifact["gaps"] if gap["source_paper_id"] == "gate-cs-2013"
    ]
    assert "gate-cs-2013" not in report["paper_gaps"]


def test_known_2020_pre_final_secondary_disagreements_are_reported(built: tuple[dict, dict]) -> None:
    artifact, _ = built
    assert [
        (row["source_paper_id"], row["canonical_ordinal"], row["kind"])
        for row in artifact["conflicts"]
    ] == [
        ("gate-cs-2020", 17, "secondary_disagrees_with_official"),
        ("gate-cs-2020", 31, "secondary_disagrees_with_official"),
    ]
    assert _resolution(artifact, "gate-cs-2020", 17)["status"] == "official"
    assert _resolution(artifact, "gate-cs-2020", 31)["status"] == "official"


def test_source_hash_tampering_is_rejected_before_pdf_parsing(tmp_path: Path) -> None:
    path = tmp_path / "not-the-reviewed-key.pdf"
    path.write_bytes(b"x")
    source = MODULE.KeySource(
        paper_id="gate-cs-test",
        year=2025,
        role="answer_key",
        raw_path=str(path),
        path=path,
        sha256=hashlib.sha256(b"different").hexdigest(),
        expected_bytes=1,
        expected_pages=1,
        authority="primary_official",
        authority_level="official",
        source_url=None,
        index_url=None,
        parser_profile="structured_global_session_1",
    )
    with pytest.raises(MODULE.AnswerKeyIndexError, match="SHA-256 mismatch"):
        MODULE._validate_source(source)
