# gallery-dedup

Pure Python algorithms for manga/doujinshi gallery title normalization, artist extraction, and duplicate clustering across galleries.

Zero external dependencies.

## Installation

```bash
pip install gallery-dedup
```

Or with `uv`:

```bash
uv add gallery-dedup
```

## Features

- **Title Normalization**: NFKC-folds full-width characters, lowercases, strips noise tags (e.g. `[DL版]`, `[無修正]`, `[中国翻訳]`), brackets, and punctuation, preserving CJK and Hangul (Hangul counts as a wide character, same as CJK).
- **Artist Extraction**: Extracts author/circle names from standard formats like `[Circle (Artist)]`, `[Artist]`, `【Circle (Artist)】`, `（Artist）`, or `Artist - Title` (guarded: the remainder must still have a usable core).
- **Noise Guard**: Version/translation brackets (`[DL版]`, `[無修正]`, `[中国翻訳]`, `[English]`, ...) never become artists. `is_noise_bracket()` and `NOISE_BRACKET_TOKENS` expose the rule.
- **Duplicate Clustering**: Multi-pass clustering of gallery items based on primary core titles, alternate core titles, and matched artists; groups that share a gallery gid are union-merged so one gallery appears in exactly one group.
- **Deterministic Output**: Buckets are iterated in sorted order and keys are chosen by a stable rank, so results do not depend on `PYTHONHASHSEED`.
- **Duplicate Scoring**: `calculate_duplicate_score()` and `DUP_SCORE_THRESHOLD` are **informational only** — the clustering code does not call them. They are kept for API compatibility.

## Usage

```python
from gallery_dedup import (
    normalize_title,
    artist_from_title,
    extract_duplicate_artist_and_core,
    find_gallery_duplicate_groups,
)

norm = normalize_title("[Circle (Artist)] Sample Work [DL版]")
# => "samplework"

artist = artist_from_title("[Circle (Artist)] Sample Work")
# => "artist"

artist, pri_core, alts = extract_duplicate_artist_and_core("[Artist] Title (Alt Title)")
```

## 0.2.0 behavior changes

- Leading noise brackets (`[DL版]`, `[無修正]`, `[中国翻訳]`, `【DL版】`, ...) are stripped before artist parsing, so `[DL版] Secret Story` has an empty artist and groups with `[Artist] Secret Story`.
- `【...】` corner brackets are recognized as circle/artist prefixes, like `[...]`.
- `normalize_title` applies NFKC folding: `ＡＢＣ ＤＥＦ` → `abcdef`; Hangul is preserved (`사랑해요 우리` → `사랑해요우리`).
- `A - B` splitting is guarded: it only splits when the right side still has a core of at least `DUP_CORE_MIN_EFFECTIVE_LEN` effective characters (and the left side looks like an artist prefix), so `Secret Story - 前編` keeps its full core.
- Groups sharing at least one gid are union-merged (one gallery appears once); groups with disjoint gids are not bridged by empty artists.
- `calculate_duplicate_score()` / `DUP_SCORE_THRESHOLD` remain public but are documented as informational only and are not used for clustering.
