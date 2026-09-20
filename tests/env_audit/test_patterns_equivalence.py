import re

import pytest

from envaudit.core import patterns

from .canaries import CANARY_CLASSES, canary


LEFT_BOUNDARY = rb"(?<![A-Za-z0-9_-])"
RIGHT_BOUNDARY = rb"(?![A-Za-z0-9_-])"
REFERENCE_CLASSES = (
    ("bitrix_webhook", re.compile(rb"/rest/[0-9]+/[a-z0-9]{12,}/?"), True),
    (
        "tg_bot_token",
        re.compile(LEFT_BOUNDARY + rb"[0-9]{8,10}:[A-Za-z0-9_-]{35}" + RIGHT_BOUNDARY),
        True,
    ),
    (
        "anthropic_key",
        re.compile(LEFT_BOUNDARY + rb"sk-ant-[A-Za-z0-9_-]{20,}" + RIGHT_BOUNDARY),
        True,
    ),
    (
        "openai_key",
        re.compile(LEFT_BOUNDARY + rb"sk-(?!ant-)[A-Za-z0-9_-]{20,}" + RIGHT_BOUNDARY),
        True,
    ),
    (
        "github_token",
        re.compile(LEFT_BOUNDARY + rb"gh[pousr]_[A-Za-z0-9]{36}" + RIGHT_BOUNDARY),
        True,
    ),
    (
        "jwt",
        re.compile(
            LEFT_BOUNDARY
            + rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
            + RIGHT_BOUNDARY
        ),
        True,
    ),
    ("private_key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), True),
    (
        "api_key_assignment",
        re.compile(
            rb"api[_-]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{16,}",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "basic_auth_url",
        re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@"),
        True,
    ),
    (
        "generic_assignment",
        re.compile(rb"(key|token|secret|password)\s*[=:]\s*\S{8,}", re.IGNORECASE),
        False,
    ),
)


def _reference_find(data: bytes, *, self_check_only: bool) -> list[patterns.Match]:
    found = []
    for name, regex, self_check in REFERENCE_CLASSES:
        if self_check_only and not self_check:
            continue
        for match in regex.finditer(data):
            found.append(
                patterns.Match(
                    name,
                    data.count(b"\n", 0, match.start()) + 1,
                    match.start(),
                    match.end(),
                )
            )
    return found


def _n8n_like_data() -> bytes:
    unit = (
        b'{"nodes":[{"name":"HTTP Request","parameters":'
        b'{"url":"https://service.invalid/api/v1/items","headers":'
        b'{"api-key":"public-value"},"position":[123,456],'
        b'"type":"n8n-nodes-base.httpRequest"}}],"connections":'
        b'{"Main":{"main":[[{"node":"HTTP Request","type":"main","index":0}]]}}}\n'
    )
    size = 2 * 1024 * 1024
    data = bytearray((unit * (size // len(unit) + 1))[:size])
    boundaries = (31, 256, 4096, 8192, 16384, 32768, 65536, 131072, 524288, size - 64)
    for index, (cls, boundary) in enumerate(zip(CANARY_CLASSES, boundaries)):
        value = canary(cls, index + 100).encode("ascii")
        marker = b"://" if cls == "basic_auth_url" else b":" if cls == "tg_bot_token" else value[:1]
        marker_at = value.index(marker)
        payload = b" " + value + b" "
        start = boundary - marker_at - 1
        data[start : start + len(payload)] = payload
    return bytes(data)


ORDINARY_DATA = (
    b"ordinary prose\n"
    b"1https://alice:correct-horse@service.invalid/\n"
    b" 12345678:AbCdEfGhIjKlMnOpQrStUvWxYz012345678 "
    b"12345678901:AbCdEfGhIjKlMnOpQrStUvWxYz012345678\n"
)


@pytest.mark.parametrize("self_check_only", [False, True])
@pytest.mark.parametrize(
    "data",
    [ORDINARY_DATA, _n8n_like_data()],
    ids=["ordinary", "n8n_2mib"],
)
def test_find_matches_reference(data, self_check_only):
    assert patterns.find(data, self_check_only=self_check_only) == _reference_find(
        data,
        self_check_only=self_check_only,
    )
