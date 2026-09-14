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

- **Title Normalization**: Lowercases, strips noise tags (e.g. `[DL版]`, `[無修正]`), brackets, and punctuation, preserving CJK characters.
- **Artist Extraction**: Extracts author/circle names from standard formats like `[Circle (Artist)]`, `[Artist]`, `(Artist)`, or `Artist - Title`.
- **Duplicate Clustering**: Multi-pass clustering of gallery items based on primary core titles, alternate core titles, and matched artists.
- **Duplicate Scoring & Filtering**: Duplicate scoring heuristic and group ignore utilities.

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
