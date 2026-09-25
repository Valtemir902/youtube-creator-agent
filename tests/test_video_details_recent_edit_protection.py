from creator_service.cloud_mcp_server_video import _owned_video_details


class _Service:
    def _owned_video_item(self, video_id, *, part):
        assert video_id == "video-1"
        return {
            "id": video_id,
            "snippet": {
                "channelId": "channel-1",
                "title": "Video",
                "description": "",
                "tags": [],
                "categoryId": "22",
                "thumbnails": {},
            },
            "contentDetails": {},
            "statistics": {},
            "status": {
                "uploadStatus": "processed",
                "privacyStatus": "public",
            },
            "player": {},
            "recordingDetails": {},
            "topicDetails": {},
        }

    def video_memory_state(self, video_id):
        assert video_id == "video-1"
        return {
            "protected": False,
            "video_id": video_id,
            "last_action_at": None,
            "seconds_remaining": 0,
            "protection_hours": 24,
            "last_action_type": None,
            "last_changed_fields": [],
        }


def test_owned_video_details_exposes_recent_edit_protection():
    details = _owned_video_details(_Service(), "video-1")

    assert details["upload_status"] == "processed"
    assert details["recent_edit_protection"]["protected"] is False
    assert details["recent_edit_protection"]["seconds_remaining"] == 0
