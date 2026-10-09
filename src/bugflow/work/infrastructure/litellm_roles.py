"""Ask a LiteLLM proxy which model answers for each name it publishes.

Code that calls a model asks the proxy for a name such as "small". The
proxy's configuration decides which vendor's model answers for that
name. A completion's response repeats the name that was asked for, so
the model behind a name cannot be read from a completion. It has to be
asked for here.
"""

import httpx2


class ServingUnknownError(Exception):
    """The proxy could not be asked which model answers for each
    name."""


def served_by(client: httpx2.Client) -> dict[str, str]:
    """Return, for each name the proxy publishes, the model behind it.

    A model is given without its provider's prefix: "vendor-a/quick-1"
    is returned as "quick-1". If several deployments answer for one
    name, all of their models are given, sorted and joined with ", ".

    Returns an empty dictionary if the proxy has no ``/model/info``
    endpoint, or answers it with something that cannot be read. The
    caller then takes each name to be the model it names.

    Raises ``ServingUnknownError`` if the proxy cannot be reached or
    answers with any other error.
    """
    try:
        answer = client.get("/model/info")
    except httpx2.RequestError as exc:
        raise ServingUnknownError(str(exc)) from exc
    if answer.status_code == 404:
        return {}
    if answer.status_code >= 400:
        raise ServingUnknownError(
            f"the proxy answered {answer.status_code} when asked which "
            "model serves each name"
        )
    try:
        listed = answer.json().get("data")
    except (ValueError, AttributeError):
        return {}
    served: dict[str, set[str]] = {}
    for entry in listed if isinstance(listed, list) else []:
        name = entry.get("model_name") if isinstance(entry, dict) else None
        params = entry.get("litellm_params") or {} if name else {}
        model = params.get("model") if isinstance(params, dict) else None
        if name and model:
            served.setdefault(str(name), set()).add(
                str(model).split("/", 1)[-1]
            )
    return {name: ", ".join(sorted(models)) for name, models in served.items()}
