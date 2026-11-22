"""Gzip and ETag handling for text responses.

The page is served to a phone over Wi-Fi, so text responses are compressed and
each representation gets its own validator. The module stays free of the Flask
app: app.py wires these helpers into its after/request hooks.
"""

import gzip
import hashlib
import threading

from flask import request


# Text responses are gzipped when the client asks for it: the phone serves this
# page over a slow Wi-Fi link, so 291 KB of HTML/CSS/JS must not go out raw.
GZIP_MIMETYPES = {"text/html", "text/css", "application/javascript", "text/javascript"}
GZIP_MIN_BYTES = 1024
ASSET_GZIP_CACHE: dict[tuple[str, int, int], bytes] = {}
ASSET_GZIP_LOCK = threading.Lock()
ASSET_GZIP_CACHE_LIMIT = 8


def accepts_gzip() -> bool:
    """Report whether the client advertised gzip support."""
    return "gzip" in (request.headers.get("Accept-Encoding") or "").lower()


def gzip_body(data: bytes, cache_key: tuple[str, int, int] | None = None) -> bytes:
    """Gzip a text body, reusing the result while the source file is unchanged."""
    if cache_key is not None:
        with ASSET_GZIP_LOCK:
            cached = ASSET_GZIP_CACHE.get(cache_key)
        if cached is not None:
            return cached
    compressed = gzip.compress(data, 6, mtime=0)
    if cache_key is not None:
        with ASSET_GZIP_LOCK:
            if len(ASSET_GZIP_CACHE) >= ASSET_GZIP_CACHE_LIMIT:
                ASSET_GZIP_CACHE.clear()
            ASSET_GZIP_CACHE[cache_key] = compressed
    return compressed


def representation_etag(base_etag: str, gzipped: bool) -> str:
    """Return an ETag that identifies one representation of the same resource.

    Caches match entries by ETag, so the gzip and identity bodies must not share
    one: a client that did not ask for gzip could be handed a gzip body, or a
    revalidation could accept a body in the wrong encoding.
    """
    token = base_etag.strip()
    if token.startswith("W/"):
        token = token[2:].strip()
    token = token.strip('"')
    return f'"{token}-gzip"' if gzipped else f'"{token}"'


def compress_response(
    response,
    cache_key: tuple[str, int, int] | None = None,
    accept_ranges: bool = False,
):
    """Gzip a text response and answer preconditions for the chosen representation.

    A gzip and an identity body of the same file are different representations:
    they get different ETags, and validators, date preconditions, and byte ranges
    are judged only once the representation is known.  A conditional request is
    answered with 304 only when it names the representation this request would
    receive, so the identity ETag can never confirm a gzip body.
    """
    if response.status_code != 200 or response.headers.get("Content-Encoding"):
        return response
    if (response.mimetype or "").lower() not in GZIP_MIMETYPES:
        return response
    body = response.get_data()
    size = len(body)
    if not size:
        # A HEAD response has no body; judge the size from the declared length.
        try:
            size = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            size = 0
    gzipped = accepts_gzip() and size >= GZIP_MIN_BYTES
    base_etag = response.get_etag()[0] or hashlib.sha1(body).hexdigest()
    response.headers.add("Vary", "Accept-Encoding")
    # The value is already quoted; set_etag() would reject it as invalid.
    response.headers["ETag"] = representation_etag(base_etag, gzipped)
    if gzipped and body:
        response.set_data(gzip_body(body, cache_key))
        response.headers["Content-Encoding"] = "gzip"
    # Preconditions and ranges belong to the representation chosen above; letting
    # them run earlier would let the file's identity validators answer for gzip.
    response.make_conditional(
        request,
        accept_ranges=accept_ranges,
        complete_length=len(response.get_data()),
    )
    return response
