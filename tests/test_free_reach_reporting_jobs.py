from intelligence.free_reach_reporting import YouTubeReachReporting


class _Exec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Jobs:
    def __init__(self, parent):
        self.parent = parent

    def list(self, **kwargs):
        return _Exec({"jobs": list(self.parent.jobs_payload)})

    def create(self, **kwargs):
        self.parent.create_calls.append(kwargs)
        return _Exec({"id": "job-created", "reportTypeId": kwargs["body"]["reportTypeId"]})

    def reports(self):
        return _Reports(self.parent)


class _Reports:
    def __init__(self, parent):
        self.parent = parent

    def list(self, **kwargs):
        return _Exec({"reports": list(self.parent.reports_payload)})


class _ReportTypes:
    def __init__(self, parent):
        self.parent = parent

    def list(self, **kwargs):
        return _Exec({"reportTypes": list(self.parent.report_types_payload)})


class _ReportingClient:
    def __init__(self, *, jobs=None, report_types=None, reports=None):
        self.jobs_payload = jobs or []
        self.report_types_payload = report_types or []
        self.reports_payload = reports or []
        self.create_calls = []

    def jobs(self):
        return _Jobs(self)

    def reportTypes(self):
        return _ReportTypes(self)


def test_fetch_latest_never_creates_reporting_job_implicitly():
    client = _ReportingClient(report_types=[{"id": "channel_reach_basic_a1"}])
    reporting = YouTubeReachReporting("unused.json", reporting_client=client)

    result = reporting.fetch_latest(video_id="video-1")

    assert result["data_available"] is False
    assert result["write_required"] is True
    assert result["report_type"] == "channel_reach_basic_a1"
    assert result["writes_performed"] == 0
    assert client.create_calls == []


def test_existing_reporting_job_is_read_without_write():
    client = _ReportingClient(
        jobs=[{"id": "job-1", "reportTypeId": "channel_reach_basic_a1"}],
        reports=[],
    )
    reporting = YouTubeReachReporting("unused.json", reporting_client=client)

    result = reporting.fetch_latest(video_id="video-1")

    assert result["pending"] is True
    assert result["job_id"] == "job-1"
    assert result["writes_performed"] == 0
    assert client.create_calls == []


def test_reach_job_creation_requires_explicit_call():
    client = _ReportingClient(report_types=[{"id": "channel_reach_basic_a1"}])
    reporting = YouTubeReachReporting("unused.json", reporting_client=client)

    result = reporting.create_reach_job()

    assert result["created"] is True
    assert result["job"]["id"] == "job-created"
    assert len(client.create_calls) == 1
