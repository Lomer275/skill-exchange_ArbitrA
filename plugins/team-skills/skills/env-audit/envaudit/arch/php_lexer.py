import re


_HEREDOC = re.compile(
    rb"<<<[ \t]*(?P<quote>['\"]?)(?P<label>[A-Za-z_][A-Za-z0-9_]*)"
    rb"(?P=quote)[ \t]*(?:\r?\n|$)"
)


def _blank(output: bytearray, data: bytes, start: int, end: int) -> None:
    for index in range(start, min(end, len(output))):
        if data[index] not in (10, 13):
            output[index] = 32


def _line_end(data: bytes, start: int) -> int:
    newline = data.find(b"\n", start)
    return len(data) if newline < 0 else newline + 1


def _heredoc_end(data: bytes, start: int, label: bytes) -> int:
    position = start
    terminator = re.compile(
        rb"^[ \t]*" + re.escape(label) + rb";?[ \t]*(?:\r?\n|$)"
    )
    while position < len(data):
        end = _line_end(data, position)
        if terminator.match(data[position:end]):
            return end
        position = end
    return len(data)


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

        if data.startswith(b"?>", position):
            _blank(output, data, position, position + 2)
            position += 2
            in_php = False
            continue

        if data.startswith(b"//", position) or (
            data[position : position + 1] == b"#"
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

        if data.startswith(b"/*", position):
            close = data.find(b"*/", position + 2)
            end = len(data) if close < 0 else close + 2
            _blank(output, data, position, end)
            position = end
            continue

        quote = data[position : position + 1]
        if quote in {b"'", b'"'}:
            end = position + 1
            while end < len(data):
                if data[end : end + 1] == b"\\":
                    end += 2
                    continue
                if data[end : end + 1] == quote:
                    end += 1
                    break
                end += 1
            _blank(output, data, position, end)
            position = end
            continue

        if data.startswith(b"<<<", position):
            declaration_end = _line_end(data, position)
            match = _HEREDOC.match(data[position:declaration_end])
            if match is not None:
                end = _heredoc_end(data, declaration_end, match.group("label"))
                _blank(output, data, position, end)
                position = end
                continue

        position += 1

    return bytes(output)
