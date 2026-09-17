import re


_HEREDOC = re.compile(
    rb"<<<[ \t]*(?P<quote>['\"]?)(?P<label>[A-Za-z_][A-Za-z0-9_]*)"
    rb"(?P=quote)[ \t]*(?:\r?\n|$)"
)
_PHP_SPECIAL = re.compile(rb"\?>|//|/\*|['\"]|#|<<<")
_BLANK_TABLE = bytes.maketrans(
    bytes(range(256)),
    bytes(value if value in (10, 13) else 32 for value in range(256)),
)


def _blank(output: bytearray, data: bytes, start: int, end: int) -> None:
    bounded_end = min(end, len(output))
    output[start:bounded_end] = data[start:bounded_end].translate(_BLANK_TABLE)


def _line_end(data: bytes, start: int) -> int:
    newline = data.find(b"\n", start)
    return len(data) if newline < 0 else newline + 1


def _heredoc_end(data: bytes, start: int, label: bytes) -> int:
    terminator = re.compile(
        rb"^[ \t]*" + re.escape(label) + rb";?[ \t]*(?:\r?\n|$)",
        re.MULTILINE,
    )
    match = terminator.search(data, start)
    return match.end() if match is not None else len(data)


def _quoted_end(data: bytes, start: int, quote: bytes) -> int:
    search_from = start + 1
    while True:
        close = data.find(quote, search_from)
        if close < 0:
            return len(data)
        backslashes = 0
        position = close - 1
        while position > start and data[position] == 92:
            backslashes += 1
            position -= 1
        if backslashes % 2 == 0:
            return close + 1
        search_from = close + 1


def strip_php(data: bytes) -> bytes:
    """Keep PHP code while blanking HTML, strings, and comments byte-for-byte."""
    output = bytearray(data)
    position = 0
    in_php = False

    while position < len(data):
        if not in_php:
            tag = data.find(b"<?", position)
            if tag < 0:
                _blank(output, data, position, len(data))
                break
            _blank(output, data, position, tag)
            lowered = data[tag : tag + 5].lower()
            tag_end = tag + (
                5
                if lowered.startswith(b"<?php")
                else 3
                if data[tag : tag + 3] == b"<?="
                else 2
            )
            _blank(output, data, tag, tag_end)
            position = tag_end
            in_php = True
            continue

        special = _PHP_SPECIAL.search(data, position)
        if special is None:
            break
        position = special.start()
        token = special.group()

        if token == b"?>":
            _blank(output, data, position, position + 2)
            position += 2
            in_php = False
            continue

        if token == b"//" or (
            token == b"#"
            and data[position : position + 2] != b"#["
        ):
            end = _line_end(data, position)
            close = data.find(b"?>", position, end)
            if close >= 0:
                _blank(output, data, position, close + 2)
                position = close + 2
                in_php = False
            else:
                _blank(output, data, position, end)
                position = end
            continue

        if token == b"/*":
            close = data.find(b"*/", position + 2)
            end = len(data) if close < 0 else close + 2
            _blank(output, data, position, end)
            position = end
            continue

        if token in {b"'", b'"'}:
            end = _quoted_end(data, position, token)
            _blank(output, data, position, end)
            position = end
            continue

        if token == b"<<<":
            declaration_end = _line_end(data, position)
            match = _HEREDOC.match(data[position:declaration_end])
            if match is not None:
                end = _heredoc_end(data, declaration_end, match.group("label"))
                _blank(output, data, position, end)
                position = end
                continue

        position = special.end()

    return bytes(output)
