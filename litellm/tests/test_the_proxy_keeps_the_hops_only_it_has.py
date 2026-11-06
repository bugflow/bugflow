"""The proxy's callback: the two files of an exchange only it can write.

It runs inside LiteLLM's container, so it is tested here the way
LiteLLM calls it, with a kwargs dict of the shape the proxy passes a
logger, rather than through the proxy itself.

The rule it must never break: a call is not failed by an archive. A
judgement whose evidence could not be stored is still a judgement, and
every figure about it is journalled by the worker either way.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tokenomic_callback import (
    ARCHIVE_HEADER,
    LLM_RESPONSE,
    PROXY_REQUEST,
    TokenomicArchive,
    folder_from,
    hops,
)

FOLDER = "exchanges/2026/09/18/0f4a"

#: What the proxy hands a logger: the provider-native request it built,
#: and the provider's answer before it was normalised.
KWARGS: dict[str, Any] = {
    "litellm_call_id": "1ab39907",
    "litellm_params": {
        "metadata": {
            "headers": {ARCHIVE_HEADER: FOLDER, "authorization": "redacted"}
        }
    },
    "additional_args": {
        "complete_input_dict": {
            "contents": [{"role": "user", "parts": [{"text": "judge this"}]}],
            "generationConfig": {"temperature": 0},
        },
        "api_base": "https://generativelanguage.googleapis.com",
    },
    "original_response": json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    ),
}


class FakeS3:
    def __init__(self, explode: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.explode = explode

    def put_object(self, **kwargs: Any) -> None:
        """boto3 takes Bucket, Key and Body, capitalised as it pleases."""
        if self.explode:
            raise RuntimeError("bucket is on fire")
        self.objects[kwargs["Key"]] = kwargs["Body"]


def archive(explode: bool = False) -> tuple[TokenomicArchive, FakeS3]:
    written = FakeS3(explode)
    keeper = TokenomicArchive()
    keeper._s3, keeper._bucket = written, "exchanges"
    return keeper, written


def stored(written: FakeS3, hop: str) -> dict[str, Any]:
    return dict(
        json.loads(gzip.decompress(written.objects[f"{FOLDER}/{hop}.json.gz"]))
    )


class TestTheHopsOnlyTheProxyHas:
    def test_the_provider_native_request_is_kept(self) -> None:
        """Not a copy of what the worker sent: the provider's own body,
        which is where a question about caching or generation config is
        answered."""
        keeper, written = archive()
        keeper.log_success_event(KWARGS, object(), None, None)

        body = stored(written, PROXY_REQUEST)["body"]
        assert body["generationConfig"] == {"temperature": 0}
        assert body["contents"][0]["parts"][0]["text"] == "judge this"

    def test_the_providers_own_answer_is_kept(self) -> None:
        keeper, written = archive()
        keeper.log_success_event(KWARGS, object(), None, None)

        response = stored(written, LLM_RESPONSE)
        assert response["body"]["candidates"]
        assert response["status"] == "ok"

    def test_both_land_in_the_folder_the_worker_named(self) -> None:
        """So the five files of one exchange are one directory, whatever
        either side's clock says about the date."""
        keeper, written = archive()
        keeper.log_success_event(KWARGS, object(), None, None)

        assert sorted(written.objects) == [
            f"{FOLDER}/{LLM_RESPONSE}.json.gz",
            f"{FOLDER}/{PROXY_REQUEST}.json.gz",
        ]

    def test_the_endpoint_it_was_sent_to_is_kept(self) -> None:
        """A provider-native request that does not say which endpoint
        answered it is half a record."""
        keeper, written = archive()
        keeper.log_success_event(KWARGS, object(), None, None)

        assert stored(written, PROXY_REQUEST)["api_base"] == (
            "https://generativelanguage.googleapis.com"
        )

    def test_the_endpoint_is_found_wherever_litellm_put_it(self) -> None:
        kwargs = dict(KWARGS)
        kwargs["additional_args"] = {"complete_input_dict": {"x": 1}}
        kwargs["litellm_params"] = dict(KWARGS["litellm_params"]) | {
            "api_base": "https://api.anthropic.com"
        }

        documents = hops(kwargs, object())

        assert documents[PROXY_REQUEST]["api_base"] == (
            "https://api.anthropic.com"
        )

    def test_the_call_id_ties_them_to_the_rest(self) -> None:
        keeper, written = archive()
        keeper.log_success_event(KWARGS, object(), None, None)

        assert stored(written, PROXY_REQUEST)["call_id"] == "1ab39907"


class TestWhatItDeclinesToDo:
    def test_a_call_with_no_folder_is_not_its_business(self) -> None:
        """Something calling this proxy that keeps no archive is not
        archived by it."""
        keeper, written = archive()
        keeper.log_success_event(
            {"litellm_params": {"metadata": {}}}, object(), None, None
        )

        assert written.objects == {}

    def test_a_bucket_on_fire_does_not_fail_the_call(self) -> None:
        keeper, _ = archive(explode=True)

        keeper.log_success_event(KWARGS, object(), None, None)

    def test_a_failed_call_is_kept_too(self) -> None:
        """What the provider said about refusing is only here."""
        keeper, written = archive()
        keeper.log_failure_event(KWARGS, None, None, None)

        assert stored(written, LLM_RESPONSE)["status"] == "failed"

    def test_without_a_bucket_it_writes_nothing(self) -> None:
        """A deployment that names no bucket keeps no content, and the
        proxy answers as before."""
        keeper = TokenomicArchive()
        keeper._s3, keeper._bucket = None, None

        keeper.log_success_event(KWARGS, object(), None, None)


class TestReadingTheKwargs:
    def test_the_header_is_found_whatever_its_case(self) -> None:
        assert (
            folder_from(
                {
                    "litellm_params": {
                        "metadata": {
                            "headers": {"X-Bugflow-Archive-Folder": FOLDER}
                        }
                    }
                }
            )
            == FOLDER
        )

    def test_a_response_that_is_not_json_is_kept_as_text(self) -> None:
        """A provider erroring in HTML is when the bytes are wanted."""
        documents = hops({"original_response": "<html>502</html>"}, None)

        assert documents[LLM_RESPONSE]["body"] is None
        assert documents[LLM_RESPONSE]["text"] == "<html>502</html>"

    def test_an_absent_hop_is_written_as_null_rather_than_skipped(
        self,
    ) -> None:
        """So a reader can tell "nothing was sent" from "nobody recorded
        it"."""
        documents = hops({}, None)

        assert documents[PROXY_REQUEST]["body"] is None
