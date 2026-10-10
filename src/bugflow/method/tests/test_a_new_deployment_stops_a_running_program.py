"""Tests of the watch that stops a program when a different deployment
is put in force, so that its next start reads the new one."""

import asyncio

import pytest

from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.infrastructure.deployment_watch import (
    DeployedFrom,
    changed_since,
    stop_on_new_deployment,
    wait_for_new_deployment,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import READ

REPOSITORY = "example-org/pull-request-policies"


def deployment(commit: str) -> PolicyDeployment:
    files = READ | {"prose/doctrine/02-commit.md": f"Deployed as {commit}.\n"}
    return PolicyDeployment(
        repository=REPOSITORY,
        commit=commit,
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )


def started_with(commit: str) -> DeployedFrom:
    return DeployedFrom(
        repository=REPOSITORY,
        commit=commit,
        content_hash=deployment(commit).content_hash,
    )


def put(held: InMemoryPolicyDeployments) -> PutInForce:
    latest = held.last_put_in_force()
    assert latest is not None
    return latest


def test_no_deployment_in_the_database_is_no_change() -> None:
    assert changed_since(None, None) is False


def test_a_first_deployment_is_a_change_for_a_program_without_one() -> None:
    held = InMemoryPolicyDeployments()
    held.deploy(deployment("c1"))
    assert changed_since(None, put(held)) is True


def test_the_deployment_a_program_started_with_is_no_change() -> None:
    held = InMemoryPolicyDeployments()
    held.deploy(deployment("c1"))
    assert changed_since(started_with("c1"), put(held)) is False


def test_another_commit_is_a_change() -> None:
    held = InMemoryPolicyDeployments()
    held.deploy(deployment("c1"))
    held.deploy(deployment("c2"))
    assert changed_since(started_with("c1"), put(held)) is True


def test_the_wait_ends_when_another_deployment_is_put_in_force() -> None:
    async def scenario() -> PutInForce | None:
        held = InMemoryPolicyDeployments()
        held.deploy(deployment("c1"))
        waiting = asyncio.create_task(
            wait_for_new_deployment(started_with("c1"), held, interval=0.01)
        )
        await asyncio.sleep(0.05)
        assert not waiting.done()
        held.deploy(deployment("c2"))
        return await asyncio.wait_for(waiting, timeout=2)

    latest = asyncio.run(scenario())
    assert latest is not None and latest.commit == "c2"


def test_a_failed_check_is_reported_and_tried_again() -> None:
    class FailsOnce(InMemoryPolicyDeployments):
        failed = False

        def last_put_in_force(self) -> PutInForce | None:
            if not self.failed:
                self.failed = True
                raise ConnectionError("database is away")
            return super().last_put_in_force()

    async def scenario() -> tuple[PutInForce | None, list[str]]:
        held = FailsOnce()
        held.deploy(deployment("c2"))
        warned: list[str] = []
        latest = await asyncio.wait_for(
            wait_for_new_deployment(
                started_with("c1"), held, interval=0.01, warn=warned.append
            ),
            timeout=2,
        )
        return latest, warned

    latest, warned = asyncio.run(scenario())
    assert latest is not None and latest.commit == "c2"
    assert len(warned) == 1 and "database is away" in warned[0]


def test_the_program_is_stopped_once_and_told_why() -> None:
    async def scenario() -> tuple[int, list[str]]:
        held = InMemoryPolicyDeployments()
        held.deploy(deployment("c2"))
        stops: list[bool] = []
        said: list[str] = []
        await asyncio.wait_for(
            stop_on_new_deployment(
                lambda: stops.append(True),
                started_with("c1"),
                held,
                interval=0.01,
                say=said.append,
            ),
            timeout=2,
        )
        return len(stops), said

    stops, said = asyncio.run(scenario())
    assert stops == 1
    assert said == [
        f"deployment {REPOSITORY} at c2 is in force; "
        "stopping so the next start reads it"
    ]


def test_a_program_whose_deployment_stays_in_force_is_not_stopped() -> None:
    async def scenario() -> bool:
        held = InMemoryPolicyDeployments()
        held.deploy(deployment("c1"))
        stopped = asyncio.Event()
        watching = asyncio.create_task(
            stop_on_new_deployment(
                stopped.set, started_with("c1"), held, interval=0.01
            )
        )
        await asyncio.sleep(0.08)
        watching.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watching
        return stopped.is_set()

    assert asyncio.run(scenario()) is False


def test_a_program_stopping_for_another_reason_ends_the_wait() -> None:
    async def scenario() -> tuple[bool, list[bool]]:
        held = InMemoryPolicyDeployments()
        held.deploy(deployment("c1"))
        stopping = asyncio.Event()
        stops: list[bool] = []
        watching = asyncio.create_task(
            stop_on_new_deployment(
                lambda: stops.append(True),
                started_with("c1"),
                held,
                interval=60,
                stopping=stopping,
            )
        )
        await asyncio.sleep(0.02)
        stopping.set()
        await asyncio.wait_for(watching, timeout=2)
        return watching.done(), stops

    done, stops = asyncio.run(scenario())
    assert done is True
    assert stops == []
