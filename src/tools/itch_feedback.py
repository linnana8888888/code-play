"""
Lightweight itch.io feedback scraper.
Fetches public comments and ratings from an itch.io game page.
No auth required — public pages only.

Stdlib-only: urllib, html.parser, re. No external deps.
"""

import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

class _CommentParser(HTMLParser):
    """
    Parses itch.io game page HTML to extract public comments.

    itch.io comment structure (as of 2024):
      <div class="post_body" ...>
        <div class="author_info">
          <a class="author_name">USERNAME</a>
          <span class="post_date" title="DATETIME">...</span>
        </div>
        <div class="body">COMMENT TEXT</div>
        <!-- optional: <div class="rating_stars" data-rating="N"> -->
      </div>
    """

    def __init__(self):
        super().__init__()
        self.comments: list[dict] = []
        self._in_post_body = False
        self._in_author_name = False
        self._in_body = False
        self._in_rating_stars = False
        self._depth_post_body = 0
        self._depth_body = 0
        self._current: dict = {}
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "").split()

        self._tag_stack.append(tag)

        if "post_body" in classes:
            self._in_post_body = True
            self._depth_post_body = len(self._tag_stack)
            self._current = {"author": None, "text": None, "posted_at": None, "rating": None}

        if self._in_post_body:
            if "author_name" in classes:
                self._in_author_name = True

            if tag == "span" and "post_date" in classes:
                # posted_at is in the title attribute
                title = attr_dict.get("title", "")
                if title:
                    self._current["posted_at"] = title.strip()

            if "body" in classes and not self._in_body:
                self._in_body = True
                self._depth_body = len(self._tag_stack)
                self._current["text"] = ""

            if "rating_stars" in classes:
                rating_val = attr_dict.get("data-rating")
                if rating_val is not None:
                    try:
                        self._current["rating"] = float(rating_val)
                    except (ValueError, TypeError):
                        pass

    def handle_endtag(self, tag):
        depth = len(self._tag_stack)

        if self._in_author_name and tag == "a":
            self._in_author_name = False

        if self._in_body and depth < self._depth_body:
            self._in_body = False

        if self._in_post_body and depth < self._depth_post_body:
            self._in_post_body = False
            # Flush current comment if it has at least author or text
            if self._current.get("author") or self._current.get("text"):
                entry = {
                    "author": (self._current.get("author") or "").strip() or "unknown",
                    "text": _clean_text(self._current.get("text") or ""),
                    "posted_at": self._current.get("posted_at"),
                    "rating": self._current.get("rating"),
                }
                if entry["text"]:  # only keep comments with actual content
                    self.comments.append(entry)
            self._current = {}

        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self._in_author_name:
            self._current["author"] = (self._current.get("author") or "") + data
        if self._in_body:
            self._current["text"] = (self._current.get("text") or "") + data


class _RatingParser(HTMLParser):
    """
    Parses itch.io game page HTML to extract aggregate rating.

    itch.io rating structure:
      <div class="aggregate_rating" ...>
        <span class="rating_value">4.5</span>
        <span class="rating_count">(<span>123</span> ratings)</span>
      </div>
    Also handles:
      <div class="game_rating_summary" data-average_rating="4.5" data-rating_count="123">
    """

    def __init__(self):
        super().__init__()
        self.avg_rating: Optional[float] = None
        self.rating_count: Optional[int] = None
        self._in_rating_value = False
        self._in_rating_count = False
        self._in_count_span = False
        self._count_depth = 0
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "").split()
        self._tag_stack.append(tag)

        # data-attribute variant (more reliable)
        if "game_rating_summary" in classes or "aggregate_rating" in classes:
            avg = attr_dict.get("data-average_rating") or attr_dict.get("data-avg_rating")
            cnt = attr_dict.get("data-rating_count") or attr_dict.get("data-count")
            if avg:
                try:
                    self.avg_rating = float(avg)
                except (ValueError, TypeError):
                    pass
            if cnt:
                try:
                    self.rating_count = int(cnt)
                except (ValueError, TypeError):
                    pass

        if "rating_value" in classes:
            self._in_rating_value = True

        if "rating_count" in classes:
            self._in_rating_count = True

        if self._in_rating_count and tag == "span" and not self._in_count_span:
            self._in_count_span = True
            self._count_depth = len(self._tag_stack)

    def handle_endtag(self, tag):
        depth = len(self._tag_stack)
        if self._in_rating_value and tag == "span":
            self._in_rating_value = False
        if self._in_count_span and depth < self._count_depth:
            self._in_count_span = False
            self._in_rating_count = False
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self._in_rating_value and self.avg_rating is None:
            try:
                self.avg_rating = float(data.strip())
            except (ValueError, TypeError):
                pass
        if self._in_count_span and self.rating_count is None:
            try:
                self.rating_count = int(data.strip().replace(",", ""))
            except (ValueError, TypeError):
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def _fetch_html(url: str, timeout: int = 15) -> str:
    """
    Fetch HTML from a URL using urllib.
    Raises urllib.error.URLError / urllib.error.HTTPError on failure.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; code-play-feedback-bot/1.0; "
                "+https://github.com/code-play)"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = "utf-8"
        content_type = resp.headers.get_content_type() or ""
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].strip()
        return resp.read().decode(charset, errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_itch_comments(itch_url: str, max_comments: int = 20) -> list[dict]:
    """
    Scrape public comments from an itch.io game page.

    Returns list of dicts:
        {author: str, text: str, posted_at: str|None, rating: float|None}

    Returns empty list on any error (graceful degradation).
    """
    if not itch_url:
        return []

    try:
        html = _fetch_html(itch_url)
    except Exception:
        return []

    parser = _CommentParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    return parser.comments[:max_comments]


def scrape_itch_rating(itch_url: str) -> Optional[dict]:
    """
    Scrape aggregate rating from an itch.io game page.

    Returns: {"avg_rating": float, "rating_count": int}
    Returns None if no rating data is available or on any error.
    """
    if not itch_url:
        return None

    try:
        html = _fetch_html(itch_url)
    except Exception:
        return None

    parser = _RatingParser()
    try:
        parser.feed(html)
    except Exception:
        return None

    if parser.avg_rating is None and parser.rating_count is None:
        return None

    return {
        "avg_rating": parser.avg_rating,
        "rating_count": parser.rating_count,
    }


def fetch_itch_feedback(itch_url: str) -> dict:
    """
    Main entry point. Fetches comments and rating from an itch.io game page.

    Returns:
        {
            "url": str,
            "fetched_at": str (ISO 8601 UTC),
            "rating": {"avg_rating": float, "rating_count": int} | None,
            "comments": list[dict],
            "comment_count": int,
            "error": str | None,
        }

    Never raises — all errors are captured in the "error" field.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()

    if not itch_url or not itch_url.strip():
        return {
            "url": itch_url,
            "fetched_at": fetched_at,
            "rating": None,
            "comments": [],
            "comment_count": 0,
            "error": "empty or missing itch_url",
        }

    url = itch_url.strip()

    # Fetch HTML once and parse both comments and rating from it
    try:
        html = _fetch_html(url)
    except urllib.error.HTTPError as e:
        return {
            "url": url,
            "fetched_at": fetched_at,
            "rating": None,
            "comments": [],
            "comment_count": 0,
            "error": f"HTTP {e.code}: {e.reason}",
        }
    except urllib.error.URLError as e:
        return {
            "url": url,
            "fetched_at": fetched_at,
            "rating": None,
            "comments": [],
            "comment_count": 0,
            "error": f"URL error: {e.reason}",
        }
    except Exception as e:
        return {
            "url": url,
            "fetched_at": fetched_at,
            "rating": None,
            "comments": [],
            "comment_count": 0,
            "error": f"{type(e).__name__}: {e}",
        }

    # Parse comments
    comment_parser = _CommentParser()
    try:
        comment_parser.feed(html)
        comments = comment_parser.comments[:20]
    except Exception as e:
        comments = []

    # Parse rating
    rating_parser = _RatingParser()
    rating: Optional[dict] = None
    try:
        rating_parser.feed(html)
        if rating_parser.avg_rating is not None or rating_parser.rating_count is not None:
            rating = {
                "avg_rating": rating_parser.avg_rating,
                "rating_count": rating_parser.rating_count,
            }
    except Exception:
        rating = None

    return {
        "url": url,
        "fetched_at": fetched_at,
        "rating": rating,
        "comments": comments,
        "comment_count": len(comments),
        "error": None,
    }
