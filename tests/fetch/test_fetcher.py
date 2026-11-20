from infrasales.fetch.fetcher import Response


def test_a_response_tells_its_media_type_and_charset_from_the_content_type() -> None:
    headers = {"content-type": 'Text/HTML; charset="ISO-8859-1"'}
    response = Response("https://news.test/a", "https://news.test/a", 200, headers, b"")

    assert (response.media_type, response.charset) == ("text/html", "iso-8859-1")
    assert not response.not_modified
