"""Evaluation tools relay the API's JSON under the caller's identity."""

import re
from urllib.parse import quote

import httpx2
from mcp.server.mcpserver.exceptions import ToolError

from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.services.bearer_token import BearerTokenService
from bugflow.shared.domain.services.token_exchange import TokenExchangeService


class EvaluationTools:
    def __init__(
        self,
        api: httpx2.Client,
        exchange: TokenExchangeService,
        api_tokens: BearerTokenService,
    ) -> None:
        self._api = api
        self._exchange = exchange
        self._api_tokens = api_tokens

    def _get(
        self,
        token: str,
        subject: str,
        path: str,
        params: list[tuple[str, str]],
    ) -> str:
        try:
            exchanged = self._exchange.exchange(token)
            caller = self._api_tokens.verify(exchanged)
            if not subject or caller.subject != subject:
                raise TokenRefusedError("the exchanged subject differs")
        except TokenRefusedError:
            raise ToolError(
                "token exchange did not preserve your identity"
            ) from None
        try:
            response = self._api.get(
                path,
                params=tuple(params),
                headers={"Authorization": f"Bearer {exchanged}"},
                follow_redirects=False,
            )
        except httpx2.HTTPError:
            raise ToolError(
                "the evaluation API could not be reached"
            ) from None
        if response.status_code != 200:
            messages = {
                401: "the API refused the exchanged token",
                403: "you may not read every requested pull request",
                404: "no evaluation was recorded in this scope",
                413: "the requested evidence exceeds the API limit",
                422: "the API refused the evaluation selectors",
            }
            raise ToolError(
                messages.get(
                    response.status_code,
                    f"the evaluation API answered {response.status_code}",
                )
            )
        # One text block preserves the JSON document without SDK reshaping.
        return response.text

    @staticmethod
    def _path(forge: str, owner: str, repo: str) -> str:
        if forge not in {"github", "forgejo"} or any(
            not re.fullmatch(r"[\w.-]{1,255}", part) or part in {".", ".."}
            for part in (owner, repo)
        ):
            raise ToolError(
                "a supported forge and owner/repository are required"
            )
        return "/api/repositories/" + "/".join(
            quote(part, safe="") for part in (forge, owner, repo)
        )

    def history(
        self,
        token: str,
        subject: str,
        forge: str,
        owner: str,
        repo: str,
        pr_numbers: list[int],
        policy_id: str | None = None,
    ) -> str:
        path = self._path(forge, owner, repo) + "/evaluations"
        if not 1 <= len(pr_numbers) <= 100 or any(
            type(number) is not int or number < 1 for number in pr_numbers
        ):
            raise ToolError("select between 1 and 100 positive PR numbers")
        params = [("pr_number", str(number)) for number in pr_numbers]
        if policy_id is not None:
            params.append(("policy_id", policy_id))
        return self._get(token, subject, path, params)

    def detail(
        self,
        token: str,
        subject: str,
        forge: str,
        owner: str,
        repo: str,
        pr_number: int,
        workflow_id: str,
        run_id: str,
    ) -> str:
        path = self._path(forge, owner, repo)
        if type(pr_number) is not int or pr_number < 1:
            raise ToolError("a positive PR number is required")
        if not workflow_id.strip() or not run_id.strip():
            raise ToolError("workflow and run identifiers are required")
        return self._get(
            token,
            subject,
            path + f"/pull-requests/{pr_number}/evaluation",
            [("workflow_id", workflow_id), ("run_id", run_id)],
        )
