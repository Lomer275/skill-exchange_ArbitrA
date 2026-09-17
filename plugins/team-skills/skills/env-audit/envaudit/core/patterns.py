from dataclasses import dataclass
import re


LEFT_BOUNDARY = rb"(?<![A-Za-z0-9_-])"
RIGHT_BOUNDARY = rb"(?![A-Za-z0-9_-])"


@dataclass(frozen=True)
class SecretClass:
    name: str
    regex: re.Pattern[bytes]
    prefilter: tuple[bytes, ...]
    self_check: bool


def _bounded(body: bytes) -> re.Pattern[bytes]:
    return re.compile(LEFT_BOUNDARY + body + RIGHT_BOUNDARY)


CLASSES = (
    SecretClass(
        "bitrix_webhook",
        re.compile(rb"/rest/[0-9]+/[a-z0-9]{12,}/?"),
        (b"/rest/",),
        True,
    ),
    SecretClass(
        "tg_bot_token",
        _bounded(rb"[0-9]{8,10}:[A-Za-z0-9_-]{35}"),
        (b":",),
        True,
    ),
    SecretClass(
        "anthropic_key",
        _bounded(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
        (b"sk-ant-",),
        True,
    ),
    SecretClass(
        "openai_key",
        _bounded(rb"sk-(?!ant-)[A-Za-z0-9_-]{20,}"),
        (b"sk-",),
        True,
    ),
    SecretClass(
        "github_token",
        _bounded(rb"gh[pousr]_[A-Za-z0-9]{36}"),
        (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_"),
        True,
    ),
    SecretClass(
        "jwt",
        _bounded(
            rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        (b"eyJ",),
        True,
    ),
    SecretClass(
        "private_key",
        re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        (b"PRIVATE KEY",),
        True,
    ),
    SecretClass(
        "api_key_assignment",
        re.compile(
            rb"api[_-]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{16,}",
            re.IGNORECASE,
        ),
        (b"api", b"API", b"Api"),
        True,
    ),
    SecretClass(
        "basic_auth_url",
        re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@"),
        (b"://",),
        True,
    ),
    SecretClass(
        "generic_assignment",
        re.compile(rb"(key|token|secret|password)\s*[=:]\s*\S{8,}", re.IGNORECASE),
        (),
        False,
    ),
)


@dataclass(frozen=True)
class Match:
    cls: str
    line: int
    start: int
    end: int


def find(data: bytes, *, self_check_only: bool = False) -> list[Match]:
    matches = []
    for secret_class in CLASSES:
        if self_check_only and not secret_class.self_check:
            continue
        if secret_class.prefilter and not any(
            marker in data for marker in secret_class.prefilter
        ):
            continue
        for match in secret_class.regex.finditer(data):
            matches.append(
                Match(
                    secret_class.name,
                    data.count(b"\n", 0, match.start()) + 1,
                    match.start(),
                    match.end(),
                )
            )
    return matches


def _monotonic_runs(value: bytes) -> list[int]:
    runs = []
    current = 1
    for previous, item in zip(value, value[1:]):
        same_kind = (
            48 <= previous <= 57 and 48 <= item <= 57
        ) or (
            65 <= previous <= 90 and 65 <= item <= 90
        ) or (
            97 <= previous <= 122 and 97 <= item <= 122
        )
        if same_kind and item == previous + 1:
            current += 1
        else:
            if current >= 10:
                runs.append(current)
            current = 1
    if current >= 10:
        runs.append(current)
    return runs


def is_fake(value: bytes) -> bool:
    lowered = value.lower()
    if re.search(rb"(.)\1{5,}", lowered, re.DOTALL):
        return True
    if any(
        marker in lowered
        for marker in (b"example", b"your", b"dummy", b"fake", b"test", b"placeholder")
    ):
        return True
    runs = _monotonic_runs(value)
    return bool(runs) and (max(runs) >= 20 or sum(runs) >= len(value) / 2)


def webhook_user_id(value: bytes) -> int | None:
    match = re.search(rb"/rest/([0-9]+)/[a-z0-9]{12,}/?", value)
    return int(match.group(1)) if match else None
