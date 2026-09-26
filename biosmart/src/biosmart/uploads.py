"""Multipart form bodies for the localhost host.

The server environment does not depend on python-multipart. Uploads are the
supplier file and the Target file. Field names and file names stay in the form.
"""

from __future__ import annotations

import re

_BOUNDARY = re.compile(r"""boundary="([^"]+)"|boundary=([^;\s]+)""", re.IGNORECASE)
_NAME = re.compile(r"""\bname="([^"]*)\"""")
_FILENAME = re.compile(r"""\bfilename="([^"]*)\"""")


class MultipartError(ValueError):
    """The body is not a multipart form this host can read."""


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, str | None, bytes]]:
    """Return ``(name, filename or None, payload)`` for each part.

    ``filename`` is set only for a file part. A text field has ``filename is None``.
    """
    if not isinstance(content_type, str) or not isinstance(body, bytes):
        raise TypeError("content_type must be a string and body must be bytes")
    if not content_type.lower().startswith("multipart/form-data"):
        raise MultipartError("Upload a file")
    match = _BOUNDARY.search(content_type)
    if match is None:
        raise MultipartError("Upload a file")
    token = match.group(1) if match.group(1) is not None else match.group(2)
    if not token or token.startswith('"'):
        raise MultipartError("Upload a file")
    try:
        delimiter = b"--" + token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise MultipartError("Upload a file") from exc
    parts: list[tuple[str, str | None, bytes]] = []
    for chunk in body.split(delimiter):
        if chunk.startswith(b"--"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        header_blob, separator, payload = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        try:
            headers = header_blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MultipartError("Upload a file") from exc
        disposition = ""
        for line in headers.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        if not disposition:
            continue
        name_match = _NAME.search(disposition)
        if name_match is None or not name_match.group(1):
            continue
        file_match = _FILENAME.search(disposition)
        filename = file_match.group(1) if file_match is not None else None
        if filename == "":
            filename = None
        parts.append((name_match.group(1), filename, payload))
    if not parts:
        raise MultipartError("Upload a file")
    return parts
