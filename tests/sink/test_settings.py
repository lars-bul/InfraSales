from infrasales.sink.settings import SinkSettings


def test_the_sink_defaults_to_the_containers_volume() -> None:
    assert SinkSettings().uri == "file:///data/sink"
