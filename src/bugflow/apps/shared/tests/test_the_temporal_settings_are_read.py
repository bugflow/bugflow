"""The Temporal settings a program reads, and their defaults."""

from bugflow.apps.shared.temporal import DEFAULT_TASK_QUEUE, TemporalSettings


def test_an_empty_environment_names_a_server_on_this_host() -> None:
    settings = TemporalSettings.from_environment({})
    assert settings == TemporalSettings(
        address="localhost:7233",
        namespace="default",
        task_queue=DEFAULT_TASK_QUEUE,
        ui_url="http://localhost:8080",
    )


def test_each_setting_is_read_from_its_variable() -> None:
    settings = TemporalSettings.from_environment(
        {
            "TEMPORAL_ADDRESS": "temporal.example:7233",
            "TEMPORAL_NAMESPACE": "reviews",
            "TEMPORAL_TASK_QUEUE": "a-queue",
            "TEMPORAL_UI_URL": "https://temporal.example",
        }
    )
    assert settings == TemporalSettings(
        address="temporal.example:7233",
        namespace="reviews",
        task_queue="a-queue",
        ui_url="https://temporal.example",
    )


def test_a_variable_set_to_nothing_is_the_default() -> None:
    assert (
        TemporalSettings.from_environment(
            {"TEMPORAL_TASK_QUEUE": ""}
        ).task_queue
        == DEFAULT_TASK_QUEUE
    )


def test_a_runs_history_is_addressed_in_the_ui() -> None:
    settings = TemporalSettings.from_environment(
        {"TEMPORAL_UI_URL": "https://temporal.example"}
    )
    assert settings.history_url("pr/github/o/r/6", "run-1") == (
        "https://temporal.example/namespaces/default/workflows/"
        "pr%2Fgithub%2Fo%2Fr%2F6/run-1/history"
    )
