"""What the research helper may connect to (Phase 12): URL rules and connect-time addresses."""

from __future__ import annotations

import pytest

from lazis.providers.web.guard import EgressRefused, address_allowed, check_url


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://tr.wikipedia.org/w/api.php", "url_scheme"),
        ("file:///etc/passwd", "url_scheme"),
        ("ftp://tr.wikipedia.org/", "url_scheme"),
        ("javascript:alert(1)", "url_scheme"),
        ("https://user:pw@tr.wikipedia.org/", "url_credentials"),
        ("https://tr.wikipedia.org:8443/", "url_port"),
        ("https://127.0.0.1/", "url_ip_literal"),
        ("https://[::1]/", "url_ip_literal"),
        ("https://10.0.0.5/", "url_ip_literal"),
        ("https://169.254.169.254/latest/meta-data", "url_ip_literal"),
        ("https://localhost/", "url_local"),
        ("https://printer.local/", "url_local"),
        ("https://intranet/", "url_local"),
        ("https://example.com/", "url_host_not_allowed"),
        ("https://tr.wikipedia.org.evil.com/", "url_host_not_allowed"),
        ("https://tr.wikipedia.org:abc/", "url_invalid"),
        ("https://tr.wikipedia.org/" + "a" * 3000, "url_too_long"),
    ],
)
def test_refused_urls(url: str, code: str) -> None:
    with pytest.raises(EgressRefused) as caught:
        check_url(url)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "url",
    ["https://tr.wikipedia.org/w/api.php?action=query", "https://en.wikipedia.org:443/wiki/X",
     "https://TR.Wikipedia.org/wiki/Ankara"],
)  # fmt: skip
def test_allowed_urls(url: str) -> None:
    assert check_url(url) == url


@pytest.mark.parametrize(
    ("ip", "port", "ok"),
    [
        ("185.15.59.224", 443, True),  # a public address
        ("2a02:ec80:300:ed1a::1", 443, True),
        ("185.15.59.224", 80, False),
        ("127.0.0.1", 443, False),
        ("10.1.2.3", 443, False),
        ("172.16.0.1", 443, False),
        ("192.168.1.1", 443, False),
        ("169.254.169.254", 443, False),
        ("100.64.0.1", 443, False),
        ("0.0.0.0", 443, False),
        ("224.0.0.1", 443, False),
        ("192.0.2.1", 443, False),
        ("::1", 443, False),
        ("fe80::1%en0", 443, False),
        ("fd00::1", 443, False),
        ("::ffff:127.0.0.1", 443, False),
        ("::ffff:10.0.0.1", 443, False),
        ("not-an-ip", 443, False),
    ],
)
def test_connect_time_addresses(ip: str, port: int, ok: bool) -> None:
    assert address_allowed(ip, port) is ok
