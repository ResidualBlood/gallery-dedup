from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

DUP_SCORE_THRESHOLD = 50  # informational only; clustering ignores this score
DUP_SCORE_ARTIST_SAME = 30
DUP_SCORE_ARTIST_ONE_EMPTY = 20
DUP_SCORE_CORE_EXACT = 35
DUP_CORE_MIN_EFFECTIVE_LEN = 6

_VERSION_TAG = re.compile(r"\[([^\]]*)\]")
_BRACKETED = re.compile(r"[\[\]()【】（）［］]")
_GROUP_LEAD = re.compile(
    r"^\s*(?:\[([^\]]*)\]|\(([^)]*)\)|【([^】]*)】|（([^）]*)）)\s*"
)

_LEADING_EVENT_RE = re.compile(r"^\s*[\(（][^\)）]+[\)）]\s*")
_BRACKET_SEGMENT_RE = re.compile(r"[\(\[\{（【［][^\)\]\}）】］]*[\)\]\}）】］]")
_HANGUL_RANGES = (
    (0xAC00, 0xD7A3),
    (0x1100, 0x11FF),
    (0x3130, 0x318F),
)

#: Bracket contents treated as version/translation noise rather than artists.
#: Compared after :func:`fold_title_text` with whitespace/separators removed.
NOISE_BRACKET_TOKENS: frozenset[str] = frozenset(
    {
        "dl版",
        "無修正",
        "無修",
        "无修正",
        "无修",
        "动态压缩版",
        "动态版",
        "aigenerated",
        "ai生成",
        "中国翻訳",
        "中国翻译",
        "中文翻译",
        "漢化",
        "汉化",
        "english",
        "chinese",
        "japanese",
        "sample",
        "サンプル",
        "見本",
    }
)


def _normalize_bracket_text(text: str) -> str:
    return re.sub(r"[\s_\-・.]+", "", fold_title_text(text))


def is_noise_bracket(text: str) -> bool:
    """Return True when *text* is a version/translation noise token.

    Surrounding brackets are tolerated. Matching uses the NFKC-folded text with
    whitespace and separators removed, so ``DL版``/``［ＤＬ版］``/``【DL版】``
    all match.
    """
    value = (text or "").strip()
    while len(value) >= 2 and value[0] in "[(【［{" and value[-1] in "])】］}":
        value = value[1:-1].strip()
    normalized = _normalize_bracket_text(value)
    if not normalized:
        return False
    return any(
        normalized == token or normalized.startswith(token)
        for token in NOISE_BRACKET_TOKENS
    )


def fold_title_text(text: str) -> str:
    """NFKC-fold and casefold *text*.

    Full-width alphanumerics become ASCII and full-width brackets become ASCII
    brackets, so differently encoded titles share one normalized core. Hangul
    is preserved by :func:`normalize_title`.
    """
    return unicodedata.normalize("NFKC", text or "").casefold()


def _is_wide_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or any(low <= code <= high for low, high in _HANGUL_RANGES)
    )


def _core_effective_length(core: str) -> int:
    """Effective length: CJK/Hangul characters count 2, everything else counts 1."""
    return sum(2 if _is_wide_char(ch) else 1 for ch in core)


def _strip_noise_brackets(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        segment = match.group(0)
        return " " if is_noise_bracket(segment[1:-1]) else segment

    return _BRACKET_SEGMENT_RE.sub(replace, text)


def normalize_title(title: str) -> str:
    """NFKC-fold, lowercase, drop everything non-alphanumeric (CJK/Hangul kept).

    Noise markers like ``[DL版]``/``【無修正】``/``[中国翻訳]`` are removed
    together with their brackets, so different versions of the same work
    collapse onto one key.
    """
    value = fold_title_text(title)
    value = _strip_noise_brackets(value)
    value = _VERSION_TAG.sub(" ", value)
    value = _BRACKETED.sub(" ", value)
    return re.sub(
        r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]+",
        "",
        value,
    )


def artist_from_title(title: str) -> str | None:
    """Best-effort artist extraction from an ExHentai-style title.

    Handles ``[Circle (Artist)]``, ``[Artist]``, ``(Artist)`` and their CJK
    bracket forms ``【Circle (Artist)】``/``（Artist）``. Noise brackets and
    ``C\\d+`` event prefixes are skipped rather than treated as artists.
    """
    cleaned = (title or "").strip()
    while True:
        lead = _GROUP_LEAD.match(cleaned)
        if not lead:
            return None
        inner = next((g for g in lead.groups() if g is not None), "").strip()
        cleaned = cleaned[lead.end() :].strip()
        if not inner or is_noise_bracket(inner) or re.fullmatch(r"[cC]\d+", inner):
            continue
        paren = re.search(r"\(([^)]+)\)", inner)
        return (paren.group(1) if paren else inner).strip().lower() or None



def extract_duplicate_artist_and_core(
    raw: str, gid: int | None = None
) -> tuple[str, str, list[str]]:
    """Extract artist, primary core, and alt_cores from raw title.

    1. DUP-STRIP-GIDPREFIX: If gid is provided and raw starts with {gid}- or {gid}_, strip it.
    2. Repeatedly strip leading ()/（） event prefixes.
    3. Strip version/translation noise brackets (动态压缩版/动态版/无修/無修正/
       AI Generated/DL版/中国翻訳/English/...), so they never become artists.
    4. Extract artist: inner of [Circle (Artist)] / [Artist] / 【Circle (Artist)】;
       else guarded ``Artist - Title`` split. Skip if inner matches C\\d+.
    5. DUP-PAREN-ALT: extract alt_cores from any (...) / （...） in remainder (effective len >= 6).
    6. Return (artist, primary_core, alt_cores).
    """
    cleaned = (raw or "").strip()

    if gid is not None:
        gid_dash = f"{gid}-"
        gid_under = f"{gid}_"
        if cleaned.startswith(gid_dash):
            cleaned = cleaned[len(gid_dash) :].strip()
        elif cleaned.startswith(gid_under):
            cleaned = cleaned[len(gid_under) :].strip()

    while True:
        m = _LEADING_EVENT_RE.match(cleaned)
        if not m:
            break
        rem = cleaned[m.end() :].strip()
        if not rem:
            break
        cleaned = rem

    cleaned = _strip_noise_brackets(cleaned).strip()

    artist = ""
    while True:
        m = re.match(r"^\s*(?:\[([^\]]+)\]|【([^】]+)】)\s*", cleaned)
        if not m:
            break
        inner = (m.group(1) or m.group(2) or "").strip()
        cleaned = cleaned[m.end() :].strip()
        if re.fullmatch(r"[cC]\d+", inner) or is_noise_bracket(inner):
            continue
        sub = re.search(r"\(([^)]+)\)", inner)
        cand = sub.group(1).strip() if sub else inner
        if cand:
            artist = cand.lower()
            break

    if not artist:
        m_dash = re.match(r"^\s*([^-–—]+?)\s*[-–—]\s*(.+)$", cleaned)
        if m_dash:
            left = m_dash.group(1).strip()
            right = m_dash.group(2).strip()
            left_is_short = " " not in left and "\u3000" not in left
            right_is_long = (
                _core_effective_length(normalize_title(right))
                >= DUP_CORE_MIN_EFFECTIVE_LEN
            )
            if left and right and (left_is_short or len(left) <= 24) and right_is_long:
                artist = left.lower()
                cleaned = right

    cleaned = _strip_noise_brackets(cleaned).strip()

    alt_cores: list[str] = []
    for m in re.finditer(r"[\(（]([^\)）]+)[\)）]", cleaned):
        inner = m.group(1).strip()
        alt_norm = normalize_title(inner)
        if (
            _core_effective_length(alt_norm) >= DUP_CORE_MIN_EFFECTIVE_LEN
            and alt_norm not in alt_cores
        ):
            alt_cores.append(alt_norm)

    primary_core = normalize_title(cleaned)
    alt_cores = [c for c in alt_cores if c != primary_core]
    return artist, primary_core, alt_cores


def calculate_duplicate_score(
    a: dict[str, Any],
    b: dict[str, Any],
) -> tuple[int, bool]:
    """Calculate an informational duplicate score and whether an edge could form.

    .. note::
        This helper is **informational only**. Duplicate clustering uses the
        bucket rules in :func:`find_duplicate_groups` /
        :func:`find_gallery_duplicate_groups` and never calls this function or
        compares against :data:`DUP_SCORE_THRESHOLD`. It is kept for backwards
        compatibility of the public API.

    Returns (score, can_edge).
    """
    artists_a = a.get("artists")
    if artists_a is None:
        art = a.get("artist")
        artists_a = {str(art).lower()} if art else set()
    else:
        artists_a = {str(x).lower() for x in artists_a if x}

    artists_b = b.get("artists")
    if artists_b is None:
        art = b.get("artist")
        artists_b = {str(art).lower()} if art else set()
    else:
        artists_b = {str(x).lower() for x in artists_b if x}

    score = 0
    if not artists_a or not artists_b:
        score += DUP_SCORE_ARTIST_ONE_EMPTY
    elif artists_a & artists_b:
        score += DUP_SCORE_ARTIST_SAME

    core_a = a.get("core", "")
    core_b = b.get("core", "")
    len_a = a.get("core_len", _core_effective_length(core_a))
    len_b = b.get("core_len", _core_effective_length(core_b))

    exact = bool(
        core_a
        and core_a == core_b
        and len_a >= DUP_CORE_MIN_EFFECTIVE_LEN
        and len_b >= DUP_CORE_MIN_EFFECTIVE_LEN
    )
    if exact:
        score += DUP_SCORE_CORE_EXACT

    can_edge = bool(exact and score >= DUP_SCORE_THRESHOLD)
    return score, can_edge


def duplicate_group_is_ignored(
    group: dict[str, Any],
    ignored_keys: set[str] | Iterable[str],
    ignored_gid_sets: list[set[int]] | Iterable[set[int]] | None = None,
) -> bool:
    """Check if a duplicate group is ignored by key, legacy_keys, or gid subset."""
    ignored_keys_set = (
        set(ignored_keys) if not isinstance(ignored_keys, set) else ignored_keys
    )
    group_key = group.get("key", "")
    if group_key in ignored_keys_set:
        return True

    legacy_keys = group.get("legacy_keys") or []
    if any(k in ignored_keys_set for k in legacy_keys):
        return True

    items = group.get("items") or []
    group_gids = {it["gid"] for it in items if "gid" in it}
    if not group_gids:
        return False

    if ignored_gid_sets:
        for ig_gids in ignored_gid_sets:
            if ig_gids and group_gids.issubset(ig_gids):
                return True

    return False


class _CandidateItem:
    def __init__(
        self,
        gid: int,
        item_dict: dict[str, Any],
        primary_cores: set[str],
        alt_cores: set[str],
        parsed_artist: str | None,
        artists: set[str],
        legacy_keys: list[str],
    ):
        self.gid = gid
        self.item_dict = item_dict
        self.primary_cores = primary_cores
        self.alt_cores = alt_cores
        self.parsed_artist = parsed_artist
        self.artists = artists
        self.legacy_keys = legacy_keys


def _group_key(group: dict[str, Any]) -> str:
    return f"{group['mode_artist']}|{group['core']}"


def _group_rank(group: dict[str, Any]) -> tuple[int, int]:
    return (1 if group["mode_artist"] else 0, len(group["core"]))


def _cluster_duplicate_candidates(candidates: list[_CandidateItem]) -> list[dict[str, Any]]:
    buckets: dict[str, list[tuple[_CandidateItem, bool]]] = defaultdict(list)
    for cand in candidates:
        for pri in sorted(cand.primary_cores):
            buckets[pri].append((cand, True))
        for alt in sorted(cand.alt_cores):
            buckets[alt].append((cand, False))

    raw_groups: list[dict[str, Any]] = []

    for core in sorted(buckets):
        bucket_items = buckets[core]
        if not any(is_pri for _, is_pri in bucket_items):
            continue

        seen_gids: set[int] = set()
        unique_items: list[tuple[_CandidateItem, bool]] = []
        for cand, is_pri in bucket_items:
            if cand.gid not in seen_gids:
                seen_gids.add(cand.gid)
                unique_items.append((cand, is_pri))

        if len(seen_gids) < 2:
            continue

        all_artists = set().union(*(c.artists for c, _ in unique_items))
        if len(all_artists) <= 1:
            cands = [c for c, _ in unique_items]
            mode_artist = ""
            if all_artists:
                target_art = next(iter(all_artists))
                parsed = [
                    c.parsed_artist
                    for c in cands
                    if c.parsed_artist and c.parsed_artist.lower() == target_art
                ]
                mode_artist = parsed[0] if parsed else target_art
            if len({c.gid for c in cands}) >= 2 and any(is_pri for _, is_pri in unique_items):
                raw_groups.append(
                    {
                        "core": core,
                        "mode_artist": mode_artist,
                        "candidates": cands,
                    }
                )
        else:
            for art in sorted(all_artists):
                sub_items = [(c, is_pri) for c, is_pri in unique_items if art in c.artists]
                sub_gids = {c.gid for c, _ in sub_items}
                if len(sub_gids) >= 2 and any(is_pri for _, is_pri in sub_items):
                    sub_cands = [c for c, _ in sub_items]
                    parsed = [
                        c.parsed_artist
                        for c in sub_cands
                        if c.parsed_artist and c.parsed_artist.lower() == art
                    ]
                    mode_artist = parsed[0] if parsed else art
                    raw_groups.append(
                        {
                            "core": core,
                            "mode_artist": mode_artist,
                            "candidates": sub_cands,
                        }
                    )
            empty_items = [(c, is_pri) for c, is_pri in unique_items if not c.artists]
            empty_gids = {c.gid for c, _ in empty_items}
            if len(empty_gids) >= 2 and any(is_pri for _, is_pri in empty_items):
                raw_groups.append(
                    {
                        "core": core,
                        "mode_artist": "",
                        "candidates": [c for c, _ in empty_items],
                    }
                )

    # Union groups that share at least one gid (same gallery listed under both
    # its English and Japanese title). Groups with disjoint gids stay separate:
    # there is deliberately no empty-artist bridging.
    parent = list(range(len(raw_groups)))

    def find(idx: int) -> int:
        while parent[idx] != idx:
            parent[idx] = parent[parent[idx]]
            idx = parent[idx]
        return idx

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    gid_owner: dict[int, int] = {}
    for idx, rg in enumerate(raw_groups):
        for cand in rg["candidates"]:
            owner = gid_owner.get(cand.gid)
            if owner is None:
                gid_owner[cand.gid] = idx
            else:
                union(owner, idx)

    components: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(raw_groups)):
        components[find(idx)].append(idx)

    result_groups: list[dict[str, Any]] = []
    for root in sorted(components):
        indices = components[root]

        best_idx = indices[0]
        for idx in indices[1:]:
            rank, best_rank = _group_rank(raw_groups[idx]), _group_rank(raw_groups[best_idx])
            if rank > best_rank or (
                rank == best_rank
                and _group_key(raw_groups[idx]) < _group_key(raw_groups[best_idx])
            ):
                best_idx = idx

        best_group = raw_groups[best_idx]
        mode_artist = best_group["mode_artist"]
        core = best_group["core"]

        merged_candidates: list[_CandidateItem] = []
        seen_merged: set[int] = set()
        for idx in indices:
            for cand in raw_groups[idx]["candidates"]:
                if cand.gid not in seen_merged:
                    seen_merged.add(cand.gid)
                    merged_candidates.append(cand)

        items = [c.item_dict for c in merged_candidates]
        items.sort(key=lambda e: (e.get("title") or "", e.get("gid", 0)))
        legacy_keys = sorted(
            {
                key
                for idx in indices
                for cand in raw_groups[idx]["candidates"]
                for key in cand.legacy_keys
            }
        )
        result_groups.append(
            {
                "key": f"{mode_artist}|{core}",
                "artist": mode_artist or None,
                "items": items,
                "legacy_keys": legacy_keys,
            }
        )

    result_groups.sort(
        key=lambda g: (
            -len(g["items"]),
            (g["items"][0].get("title") or ""),
            g["key"],
        )
    )
    return result_groups


def find_duplicate_groups(
    items: list[tuple[int, int, str, str, str, int | None, int | None, object, object]],
    *,
    gallery_titles: dict[int, tuple[str | None, str | None]],
    tag_map: dict[int, list[tuple[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    """Group favorite items that are likely the same work in different versions.

    ``items`` is ``(favcat, gid, token, title, url, gallery_id, file_size,
    first_seen_at, posted_at)``. Titles are taken from the favorite record,
    falling back to the local gallery's English then Japanese title. Items
    with no usable title are skipped.
    """
    candidates: list[_CandidateItem] = []
    for favcat, gid, token, title, url, gallery_id, file_size, first_seen_at, posted_at in items:
        eff_title = title
        if not eff_title and gallery_id is not None:
            en, jp = gallery_titles.get(gid, (None, None))
            eff_title = en or jp or ""
        if not eff_title:
            continue

        legacy_key = f"{artist_from_title(eff_title) or ''}|{normalize_title(eff_title)}"
        parsed_artist, pri_core, alt_cores = extract_duplicate_artist_and_core(eff_title, gid=gid)

        artists: set[str] = set()
        if parsed_artist:
            artists.add(parsed_artist)
        if tag_map and gallery_id is not None:
            for ns, name in tag_map.get(gallery_id, []):
                if ns and ns.lower() == "artist" and name:
                    artists.add(name.lower())

        primary_cores: set[str] = set()
        if _core_effective_length(pri_core) >= DUP_CORE_MIN_EFFECTIVE_LEN:
            primary_cores.add(pri_core)

        alt_cores_set: set[str] = {
            c
            for c in alt_cores
            if _core_effective_length(c) >= DUP_CORE_MIN_EFFECTIVE_LEN and c != pri_core
        }

        if not primary_cores and not alt_cores_set:
            continue

        item_dict = {
            "favcat": favcat,
            "gid": gid,
            "token": token,
            "title": eff_title,
            "url": url,
            "gallery_id": gallery_id,
            "file_size": file_size,
            "first_seen_at": first_seen_at,
            "posted_at": posted_at,
        }

        candidates.append(
            _CandidateItem(
                gid=gid,
                item_dict=item_dict,
                primary_cores=primary_cores,
                alt_cores=alt_cores_set,
                parsed_artist=parsed_artist or None,
                artists=artists,
                legacy_keys=[legacy_key],
            )
        )

    return _cluster_duplicate_candidates(candidates)


def find_gallery_duplicate_groups(
    galleries: list[Any],
    *,
    tag_map: dict[int, list[tuple[str, str]]] | None = None,
    fav_gids: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Group library galleries across gids that are likely the same work in different versions.

    Implements OPT-LIB-XGID:
    - Dual raw titles: title and title_jpn
    - Cores union + tag_map artist
    """
    candidates: list[_CandidateItem] = []
    for g in galleries:
        gid = getattr(g, "gid", None) if not isinstance(g, dict) else g.get("gid")
        if gid is None:
            continue
        if isinstance(g, dict):
            gallery_id = g.get("gallery_id") if "gallery_id" in g else g.get("id")
        else:
            gallery_id = getattr(g, "id", None)
        title = getattr(g, "title", None) if not isinstance(g, dict) else g.get("title")
        title_jpn = (
            getattr(g, "title_jpn", None) if not isinstance(g, dict) else g.get("title_jpn")
        )
        file_size = (
            getattr(g, "file_size", None) if not isinstance(g, dict) else g.get("file_size")
        )
        pages = (
            getattr(g, "pages", None)
            or getattr(g, "page_count", None)
            or getattr(g, "file_count", None)
            if not isinstance(g, dict)
            else (g.get("pages") or g.get("page_count") or g.get("file_count"))
        )
        if not isinstance(pages, int) or isinstance(pages, bool):
            pages = None

        category = (
            getattr(g, "category", None)
            if not isinstance(g, dict)
            else g.get("category")
        )
        if not isinstance(category, str) or not category.strip():
            category = None

        favcat = (
            getattr(g, "favcat", None)
            if not isinstance(g, dict)
            else g.get("favcat")
        )
        if not isinstance(favcat, int) or isinstance(favcat, bool):
            favcat = None

        storage_path = (
            getattr(g, "storage_path", None)
            if not isinstance(g, dict)
            else g.get("storage_path")
        )
        storage_type = (
            getattr(g, "storage_type", None)
            if not isinstance(g, dict)
            else g.get("storage_type")
        )
        url = getattr(g, "url", None) if not isinstance(g, dict) else g.get("url")
        token = getattr(g, "token", None) if not isinstance(g, dict) else g.get("token")
        thumb = getattr(g, "thumb", None) if not isinstance(g, dict) else g.get("thumb")

        if isinstance(g, dict) and "favorited" in g:
            favorited = bool(g["favorited"])
        elif fav_gids is not None:
            favorited = int(gid) in fav_gids
        else:
            favorited = False

        raws: list[str] = []
        if title and str(title).strip():
            raws.append(str(title).strip())
        if title_jpn and str(title_jpn).strip() and str(title_jpn).strip() not in raws:
            raws.append(str(title_jpn).strip())
        if not raws:
            continue

        artists: set[str] = set()
        primary_cores: set[str] = set()
        alt_cores_set: set[str] = set()
        legacy_keys: list[str] = []
        first_parsed_artist: str | None = None

        for raw in raws:
            legacy_keys.append(f"{artist_from_title(raw) or ''}|{normalize_title(raw)}")
            parsed_artist, pri_core, alts = extract_duplicate_artist_and_core(raw, gid=gid)
            if parsed_artist:
                artists.add(parsed_artist)
                if not first_parsed_artist:
                    first_parsed_artist = parsed_artist
            if _core_effective_length(pri_core) >= DUP_CORE_MIN_EFFECTIVE_LEN:
                primary_cores.add(pri_core)
            for alt in alts:
                if _core_effective_length(alt) >= DUP_CORE_MIN_EFFECTIVE_LEN:
                    alt_cores_set.add(alt)

        alt_cores_set -= primary_cores

        if tag_map and gallery_id is not None:
            for ns, name in tag_map.get(gallery_id, []):
                if ns and ns.lower() == "artist" and name:
                    artists.add(name.lower())

        if not primary_cores and not alt_cores_set:
            continue

        item_dict = {
            "gallery_id": gallery_id,
            "gid": gid,
            "title": title or title_jpn or f"gid {gid}",
            "title_jpn": title_jpn,
            "file_size": file_size,
            "pages": pages,
            "storage_path": storage_path,
            "storage_type": storage_type,
            "url": url,
            "token": token,
            "thumb": thumb,
            "favorited": favorited,
            "category": category,
            "favcat": favcat,
        }

        candidates.append(
            _CandidateItem(
                gid=gid,
                item_dict=item_dict,
                primary_cores=primary_cores,
                alt_cores=alt_cores_set,
                parsed_artist=first_parsed_artist,
                artists=artists,
                legacy_keys=legacy_keys,
            )
        )

    return _cluster_duplicate_candidates(candidates)


__all__ = [
    "DUP_CORE_MIN_EFFECTIVE_LEN",
    "DUP_SCORE_ARTIST_ONE_EMPTY",
    "DUP_SCORE_ARTIST_SAME",
    "DUP_SCORE_CORE_EXACT",
    "DUP_SCORE_THRESHOLD",
    "NOISE_BRACKET_TOKENS",
    "_CandidateItem",
    "_cluster_duplicate_candidates",
    "_core_effective_length",
    "artist_from_title",
    "calculate_duplicate_score",
    "duplicate_group_is_ignored",
    "extract_duplicate_artist_and_core",
    "find_duplicate_groups",
    "find_gallery_duplicate_groups",
    "fold_title_text",
    "is_noise_bracket",
    "normalize_title",
]
