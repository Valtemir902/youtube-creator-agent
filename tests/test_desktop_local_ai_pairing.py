from local_ai.companion import origin_allowed


def test_desktop_ephemeral_loopback_origin_is_allowed():
    assert origin_allowed("http://127.0.0.1:49152")
    assert origin_allowed("http://localhost:51789")


def test_non_loopback_dynamic_origin_is_rejected():
    assert not origin_allowed("http://192.168.1.10:49152")
    assert not origin_allowed("https://127.0.0.1:49152")
    assert not origin_allowed("http://evil.example:49152")


def test_configured_production_origin_still_allowed():
    assert origin_allowed("https://creator.silvadigitaltech.com")
