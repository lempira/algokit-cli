import json

import pytest
from algokit.core.sandbox import ALGOD_HEALTH_URL, ALGORAND_IMAGE, INDEXER_IMAGE
from pytest_httpx import HTTPXMock
from pytest_mock import MockerFixture

from tests.utils.proc_mock import ProcMock


@pytest.fixture(autouse=True)
def _algod_health_fast_timings(mocker: MockerFixture) -> None:
    mocker.patch("algokit.core.sandbox.DEFAULT_WAIT_FOR_ALGOD", 0.1)
    mocker.patch("algokit.core.sandbox.DEFAULT_HEALTH_TIMEOUT", 0.1)


@pytest.fixture()
def _health_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=ALGOD_HEALTH_URL)


@pytest.fixture()
def _localnet_up_to_date(proc_mock: ProcMock, httpx_mock: HTTPXMock) -> None:
    arg = '{{index (split (index .RepoDigests 0) "@") 1}}'
    proc_mock.set_output(
        ["docker", "image", "inspect", ALGORAND_IMAGE, "--format", arg],
        ["sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"],
    )

    proc_mock.set_output(
        ["docker", "image", "inspect", INDEXER_IMAGE, "--format", arg],
        ["sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"],
    )

    httpx_mock.add_response(
        url="https://registry.hub.docker.com/v2/repositories/algorand/indexer/tags/latest",
        json={
            "digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
    )

    httpx_mock.add_response(
        url="https://registry.hub.docker.com/v2/repositories/algorand/algod/tags/3.23.1-stable",
        json={
            "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
    )


@pytest.fixture()
def _mock_proc_with_running_localnet(proc_mock: ProcMock) -> None:
    proc_mock.set_output(
        "docker compose ls --format json --filter name=algokit_sandbox*",
        [
            json.dumps(
                [{"Name": "algokit_sandbox", "Status": "running", "ConfigFiles": "test/sandbox/docker-compose.yml"}]
            )
        ],
    )
