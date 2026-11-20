from infrasales.jobs.names import JobName


def test_each_job_is_named_as_the_api_calls_it() -> None:
    assert [job.value for job in JobName] == ["scrape", "forecast"]
