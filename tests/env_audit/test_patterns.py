import pytest

from envaudit.core.patterns import find, is_fake, webhook_user_id

from .canaries import CANARY_CLASSES, canary


@pytest.mark.parametrize("secret_class", CANARY_CLASSES)
def test_each_class_detected(secret_class):
    matches = find(("prefix " + canary(secret_class) + " suffix").encode("utf-8"))
    assert secret_class in {match.cls for match in matches}
    assert is_fake(canary(secret_class).encode("utf-8")) is False


def test_fake_filter():
    repeated = ("s" + "k-" + "a" * 30).encode("ascii")
    labelled = ("s" + "k-" + "example" + "Z7" * 12).encode("ascii")
    monotonic = ("s" + "k-" + "abcdefghijklmnopqrstuv").encode("ascii")
    assert is_fake(repeated)
    assert is_fake(labelled)
    assert is_fake(monotonic)
    assert not is_fake(canary("openai_key", seed=8).encode("ascii"))


def test_boundaries():
    body = "Z7q9" * 7
    assert "openai_key" not in {match.cls for match in find(("task-" + body).encode())}
    assert "openai_key" not in {match.cls for match in find(("x" + "sk-" + body).encode())}


def test_webhook_user_id():
    assert webhook_user_id(canary("bitrix_webhook").encode("ascii")) == 30662
