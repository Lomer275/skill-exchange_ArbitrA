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


@pytest.mark.parametrize(
    "prefix",
    [b"/", b"x/", b"`", b" ", b""],
)
def test_bitrix_rest_without_required_leading_slash(prefix):
    value = b"rest/4242/abcdefghijklmnop1234"
    matches = find(prefix + value)
    assert [match.cls for match in matches] == ["bitrix_webhook"]


@pytest.mark.parametrize(
    "data",
    [
        b"interest/12/abcdefghijklmnop",
        b"4242/a1b2c3d4e5f6g7h8",
        b"webhook 4242/abcdefghijklmnop",
        b"bitrix 4242/1234567890123456",
        b"bitrix x4242/a1b2c3d4e5f6g7h8",
    ],
)
def test_bitrix_bare_rejects_false_positives(data):
    assert "bitrix_webhook" not in {match.cls for match in find(data)}


@pytest.mark.parametrize(
    "marker",
    ["BiTrIx", "WEBhook", "ВеБхУк"],
)
def test_bitrix_bare_requires_marker_on_same_line(marker):
    value = "4242/a1b2c3d4e5f6g7h8"
    data = f"{marker}: {value}".encode("utf-8")
    matches = [match for match in find(data) if match.cls == "bitrix_webhook"]
    assert len(matches) == 1
    assert data[matches[0].start : matches[0].end] == value.encode("ascii")
    assert webhook_user_id(value.encode("ascii")) == 4242
