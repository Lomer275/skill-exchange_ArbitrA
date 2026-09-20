from envaudit.cleanup.textops import (
    compress_memory_index,
    insert_after_line,
    links,
    md_sections,
)


def test_md_sections_team_block():
    text = (
        "# Root\n"
        "## Before\nshort\n"
        "<!-- BEGIN team-context -->\n"
        "## Managed\nmanaged\n"
        "<!-- END team-context -->\n"
        "## After\nshort\n"
    )

    sections = md_sections(text)

    assert [item.title for item in sections] == ["Before", "Managed", "After"]
    assert [item.in_team_block for item in sections] == [False, True, False]


def test_compress_memory_index_keeps_links():
    text = "".join(
        f"- [карточка {number}](cards/{number}.md) {'длинный хвост ' * 10}\n"
        for number in range(260)
    )

    result, fits = compress_memory_index(text)

    assert fits is True
    assert len(result.splitlines()) <= 200
    assert len(result.encode("utf-8")) <= 25_000
    assert links(result) == links(text)


def test_insert_after_line():
    text = "one\ntwo\nthree\nfour\nfive\n"

    result = insert_after_line(text, 3, "inserted")

    assert result.splitlines()[3] == "inserted"
