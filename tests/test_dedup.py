from gallery_dedup import (
    DUP_SCORE_ARTIST_SAME,
    DUP_SCORE_CORE_EXACT,
    artist_from_title,
    calculate_duplicate_score,
    duplicate_group_is_ignored,
    extract_duplicate_artist_and_core,
    find_duplicate_groups,
    find_gallery_duplicate_groups,
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
