import hashlib
import random
import string

from envaudit.core.patterns import is_fake


CANARY_CLASSES = (
    "bitrix_webhook",
    "tg_bot_token",
    "anthropic_key",
    "openai_key",
    "github_token",
    "jwt",
    "private_key",
    "api_key_assignment",
    "basic_auth_url",
    "generic_assignment",
)


def _random_text(cls: str, length: int, seed: int, alphabet: str) -> str:
    offset = CANARY_CLASSES.index(cls) * 1009
    generator = random.Random(seed + offset)
    while True:
        value = "".join(generator.choice(alphabet) for _ in range(length))
        if not is_fake(value.encode("ascii")):
            return value


def _candidate(cls: str, seed: int) -> str:
    alphabet = string.ascii_letters + string.digits
    lower = string.ascii_lowercase + string.digits
    body = _random_text(cls, 42, seed, alphabet)
    if cls == "bitrix_webhook":
        return "/rest/30662/" + _random_text(cls, 20, seed, lower)
    if cls == "tg_bot_token":
        generator = random.Random(seed + 71)
        digits = "".join(generator.choice(string.digits) for _ in range(9))
        return digits + ":" + body[:35]
    if cls == "anthropic_key":
        return "sk" + "-ant-" + body
    if cls == "openai_key":
        return "s" + "k-" + body
    if cls == "github_token":
        return "gh" + "p_" + body[:36]
    if cls == "jwt":
        return "ey" + "J" + body[:14] + "." + body[14:28] + "." + body[28:42]
    if cls == "private_key":
        return "-----BEGIN " + "RSA " + "PRIVATE KEY-----"
    if cls == "api_key_assignment":
        return "api_" + "key=" + body
    if cls == "basic_auth_url":
        return "https" + "://" + body[:10] + ":" + body[10:24] + "@service.invalid/"
    if cls == "generic_assignment":
        return "to" + "ken=" + body
    raise KeyError(cls)


def canary(cls: str, seed: int = 0) -> str:
    for attempt in range(100):
        value = _candidate(cls, seed + attempt * 7919)
        if not is_fake(value.encode("utf-8")):
            return value
    raise RuntimeError(f"unable to construct canary for {cls}")


def fragments(value: str) -> list[str]:
    encoded = value.encode("utf-8")
    return [
        value,
        value[:8],
        value[-8:],
        hashlib.sha1(encoded).hexdigest(),
        hashlib.sha256(encoded).hexdigest(),
    ]
