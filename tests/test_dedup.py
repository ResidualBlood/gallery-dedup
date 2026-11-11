import os
import subprocess
import sys

import pytest

from gallery_dedup import (
    DUP_SCORE_ARTIST_SAME,
    DUP_SCORE_CORE_EXACT,
    NOISE_BRACKET_TOKENS,
    _core_effective_length,
    artist_from_title,
    calculate_duplicate_score,
    duplicate_group_is_ignored,
    extract_duplicate_artist_and_core,
    find_duplicate_groups,
    find_gallery_duplicate_groups,
    fold_title_text,
    is_noise_bracket,
    normalize_title,
)


def test_normalize_title():
    assert normalize_title("[Circle (Artist)] Test Title! [DL版]") == "testtitle"
    assert normalize_title("[Circle (Artist)] 魔法少女 [無修正]") == "魔法少女"
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


def test_artist_from_title():
    assert artist_from_title("[Circle (Artist)] Title") == "artist"
    assert artist_from_title("[SoloArtist] Title") == "soloartist"
    assert artist_from_title("(Artist) Title") == "artist"
    assert artist_from_title("Just Title") is None
    assert artist_from_title("") is None


def test_extract_duplicate_artist_and_core():
    # 1. Test stripping gid prefix
    artist, pri_core, alts = extract_duplicate_artist_and_core(
        "12345- [Circle (Artist)] Nice Manga (Alt Chapter Name)", gid=12345
    )
    assert artist == "artist"
    assert "nicemanga" in pri_core
    assert "altchaptername" in alts

    # 2. Test leading event stripping and noise brackets
    artist, pri_core, alts = extract_duplicate_artist_and_core(
        "(C99) [Circle (Artist)] Great Book [DL版] [无修]"
    )
    assert artist == "artist"
    assert pri_core == "greatbook"


def test_calculate_duplicate_score():
    a = {"artists": ["artist_a"], "core": "samplework", "core_len": 10}
    b = {"artists": ["artist_a"], "core": "samplework", "core_len": 10}
    score, can_edge = calculate_duplicate_score(a, b)
    assert score == DUP_SCORE_ARTIST_SAME + DUP_SCORE_CORE_EXACT
    assert can_edge is True

    # Mismatched core
    c = {"artists": ["artist_a"], "core": "differentwork", "core_len": 13}
    score_diff, can_edge_diff = calculate_duplicate_score(a, c)
    assert score_diff == DUP_SCORE_ARTIST_SAME
    assert can_edge_diff is False


def test_duplicate_group_is_ignored():
    group = {
        "key": "artist|work",
        "legacy_keys": ["artist|work_legacy"],
        "items": [{"gid": 101}, {"gid": 102}],
    }
    assert duplicate_group_is_ignored(group, ignored_keys={"artist|work"}) is True
    assert duplicate_group_is_ignored(group, ignored_keys={"artist|work_legacy"}) is True
    assert duplicate_group_is_ignored(group, ignored_keys=set()) is False

    # Check ignored gid set
    assert duplicate_group_is_ignored(group, ignored_keys=set(), ignored_gid_sets=[{101, 102, 103}]) is True
    assert duplicate_group_is_ignored(group, ignored_keys=set(), ignored_gid_sets=[{101}]) is False


def test_find_gallery_duplicate_groups():
    galleries = [
        {
            "id": 1,
            "gid": 1001,
            "title": "[Circle (Artist)] Secret Story [DL版]",
            "file_size": 1000,
        },
        {
            "id": 2,
            "gid": 1002,
            "title": "[Circle (Artist)] Secret Story [無修正]",
            "file_size": 2000,
        },
        {
            "id": 3,
            "gid": 1003,
            "title": "[OtherArtist] Completely Different Manga",
            "file_size": 3000,
        },
    ]
    groups = find_gallery_duplicate_groups(galleries)
    assert len(groups) == 1
    assert groups[0]["artist"] == "artist"
    assert len(groups[0]["items"]) == 2
    gids = {item["gid"] for item in groups[0]["items"]}
    assert gids == {1001, 1002}


def test_noise_bracket_exports():
    assert isinstance(NOISE_BRACKET_TOKENS, frozenset)
    for token in ("dl版", "無修正", "中国翻訳"):
        assert token in NOISE_BRACKET_TOKENS
    assert is_noise_bracket("DL版") is True
    assert is_noise_bracket("【中国翻訳】") is True
    assert is_noise_bracket("Circle (Artist)") is False
    assert is_noise_bracket("") is False


@pytest.mark.parametrize(
    "raw",
    [
        "[DL版] Secret Story",
        "[無修正] Secret Story",
        "[中国翻訳] Secret Story",
        "【DL版】Secret Story",
    ],
)
def test_noise_leading_bracket_is_not_artist(raw):
    artist, core, _ = extract_duplicate_artist_and_core(raw)
    assert artist == ""
    assert core == "secretstory"


def test_noise_leading_bracket_groups_with_artist_copy():
    galleries = [
        {"id": 1, "gid": 1, "title": "[DL版] Secret Story"},
        {"id": 2, "gid": 2, "title": "[Artist] Secret Story"},
    ]
    groups = find_gallery_duplicate_groups(galleries)
    assert len(groups) == 1
    assert {item["gid"] for item in groups[0]["items"]} == {1, 2}


def test_corner_bracket_circle_prefix():
    artist, core, _ = extract_duplicate_artist_and_core("【サークル】Secret Story")
    assert artist == "サークル"
    assert core == "secretstory"
    assert artist_from_title("【サークル】Secret Story") == "サークル"

    artist, core, _ = extract_duplicate_artist_and_core("[サークル (作者)] Secret Story")
    assert artist == "作者"
    assert core == "secretstory"


def test_hangul_title_kept_and_counted_as_wide():
    assert normalize_title("사랑해요 우리") == "사랑해요우리"
    artist, core, _ = extract_duplicate_artist_and_core("사랑해요 우리")
    assert artist == ""
    assert core == "사랑해요우리"
    # Hangul counts as 2 per character, same as CJK.
    assert _core_effective_length(core) == 12

    galleries = [
        {"id": 1, "gid": 1, "title": "사랑해요 우리"},
        {"id": 2, "gid": 2, "title": "사랑해요 우리 [DL版]"},
    ]
    groups = find_gallery_duplicate_groups(galleries)
    assert len(groups) == 1
    assert {item["gid"] for item in groups[0]["items"]} == {1, 2}


def test_fullwidth_nfkc_fold():
    assert fold_title_text("ＡＢＣ　ＤＥＦ") == "abc def"
    assert normalize_title("ＡＢＣ ＤＥＦ") == "abcdef"
    artist, core, _ = extract_duplicate_artist_and_core("ＡＢＣ ＤＥＦ")
    assert artist == ""
    assert core == "abcdef"


def test_dash_split_guard_rejects_short_core():
    artist, core, _ = extract_duplicate_artist_and_core("Secret Story - 前編")
    assert artist == ""
    assert core == "secretstory前編"


def test_dash_split_still_extracts_artist_with_long_core():
    artist, core, _ = extract_duplicate_artist_and_core("作者 - Secret Story")
    assert artist == "作者"
    assert core == "secretstory"


def test_shared_gid_groups_are_union_merged():
    galleries = [
        {"id": 11, "gid": 11, "title": "Secret Story", "title_jpn": "秘密の物語"},
        {"id": 12, "gid": 12, "title": "Secret Story"},
        {"id": 13, "gid": 13, "title": None, "title_jpn": "秘密の物語"},
    ]
    groups = find_gallery_duplicate_groups(galleries)
    assert len(groups) == 1
    gids = [item["gid"] for item in groups[0]["items"]]
    assert sorted(gids) == [11, 12, 13]
    assert gids.count(11) == 1


def test_union_merge_does_not_bridge_disjoint_gids():
    galleries = [
        {"id": 1, "gid": 1, "title": "[Alice] Secret Story"},
        {"id": 2, "gid": 2, "title": "[Alice] Secret Story [DL版]"},
        {"id": 3, "gid": 3, "title": "[Bob] Secret Story"},
        {"id": 4, "gid": 4, "title": "[Bob] Secret Story [DL版]"},
    ]
    groups = find_gallery_duplicate_groups(galleries)
    assert len(groups) == 2
    assert sorted(sorted(item["gid"] for item in g["items"]) for g in groups) == [[1, 2], [3, 4]]


_CLUSTER_SCRIPT = """
from gallery_dedup import find_gallery_duplicate_groups

galleries = [
    {"id": 1, "gid": 1, "title": "[Alice] Secret Story"},
    {"id": 2, "gid": 2, "title": "[Alice] Secret Story", "title_jpn": "[Alice] 秘密の物語"},
    {"id": 3, "gid": 3, "title": "[Alice] 秘密の物語"},
]
print("|".join(g["key"] for g in find_gallery_duplicate_groups(galleries)))
"""


def test_cluster_key_deterministic_across_hash_seeds():
    outputs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", _CLUSTER_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        outputs.append(proc.stdout.strip())
    assert outputs[0] == outputs[1]
    assert outputs[0] == "alice|secretstory"


def test_find_duplicate_groups():
    # items format: (favcat, gid, token, title, url, gallery_id, file_size, first_seen_at, posted_at)
    items = [
        (0, 1001, "tok1", "[Circle (Artist)] Secret Story [DL版]", "url1", 1, 1000, None, None),
        (0, 1002, "tok2", "[Circle (Artist)] Secret Story [無修正]", "url2", 2, 2000, None, None),
    ]
    groups = find_duplicate_groups(items, gallery_titles={})
    assert len(groups) == 1
    assert groups[0]["artist"] == "artist"
    assert len(groups[0]["items"]) == 2
    gids = {item["gid"] for item in groups[0]["items"]}
    assert gids == {1001, 1002}
