from creator_service.dashboard_ai import _json_object, _strip_srt


def test_json_object_accepts_fenced_json():
    value = _json_object('```json\n{"title":"x","tags":["a"]}\n```')
    assert value["title"] == "x"
    assert value["tags"] == ["a"]


def test_strip_srt_removes_timing_and_markup():
    raw = "1\n00:00:00,000 --> 00:00:01,000\n<b>Hello</b> world\n\n2\n00:00:01,000 --> 00:00:02,000\nAgain\n"
    assert _strip_srt(raw) == "Hello world Again"
