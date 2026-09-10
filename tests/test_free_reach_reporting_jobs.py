from intelligence.free_reach_reporting import YouTubeReachReporting


class Call:
    def __init__(self, value):
        self.value = value
    def execute(self):
        return self.value


class ReportCollection:
    def __init__(self, reports):
        self._reports = reports
    def list(self, **kwargs):
        return Call({"reports": self._reports})


class Jobs:
    def __init__(self, jobs=None, reports=None):
        self._jobs = list(jobs or [])
        self._reports = list(reports or [])
        self.created = []
    def list(self, **kwargs):
        return Call({"jobs": self._jobs})
    def create(self, body):
        self.created.append(dict(body))
        return Call({"id": "job-new", "reportTypeId": body["reportTypeId"], "name": body["name"]})
    def reports(self):
        return ReportCollection(self._reports)


class ReportTypes:
    def __init__(self, ids):
        self.ids = ids
    def list(self, **kwargs):
        return Call({"reportTypes": [{"id": value} for value in self.ids]})


class Client:
    def __init__(self, jobs=None, report_types=None, reports=None):
        self.jobs_resource = Jobs(jobs=jobs, reports=reports)
        self.types_resource = ReportTypes(report_types or [])
    def jobs(self):
        return self.jobs_resource
    def reportTypes(self):
        return self.types_resource


def test_reporting_reuses_existing_reach_job_without_duplicate_creation():
    client = Client(jobs=[{"id": "existing", "reportTypeId": "channel_reach_basic_a1"}])
    adapter = YouTubeReachReporting("unused.json", reporting_client=client)
    state = adapter.ensure_reach_job()
    assert state["created"] is False
    assert state["job"]["id"] == "existing"
    assert client.jobs_resource.created == []


def test_reporting_creates_one_supported_reach_job_when_missing():
    client = Client(report_types=["channel_basic_a3", "channel_reach_basic_a1"])
    adapter = YouTubeReachReporting("unused.json", reporting_client=client)
    state = adapter.ensure_reach_job()
    assert state["created"] is True
    assert state["job"]["reportTypeId"] == "channel_reach_basic_a1"
    assert len(client.jobs_resource.created) == 1


def test_new_reporting_job_returns_pending_instead_of_fake_ctr():
    client = Client(report_types=["channel_reach_basic_a1"], reports=[])
    adapter = YouTubeReachReporting("unused.json", reporting_client=client)
    result = adapter.fetch_latest(video_id="video-1")
    assert result["pending"] is True
    assert result["data_available"] is False
    assert result["writes_performed"] == 0
    assert "ainda não publicou" in result["blocked_reason"]


def test_unavailable_reach_report_type_is_explicitly_blocked():
    client = Client(report_types=["channel_basic_a3"])
    adapter = YouTubeReachReporting("unused.json", reporting_client=client)
    result = adapter.fetch_latest(video_id="video-1")
    assert result["pending"] is False
    assert result["data_available"] is False
    assert "Nenhum report type" in result["blocked_reason"]
