"""The forge context: talking to the services that host pull requests.

Words used throughout:

- Forge: a service that hosts git repositories and pull requests. GitHub
  and Forgejo are the two supported.
- Delivery: one event a forge reports, such as "a pull request was
  opened" or "a comment was added". A forge sends deliveries to a URL of
  ours, called a webhook. Each delivery has an id, and a forge that
  sends one again repeats the id.
- Webhook: a setting on a repository that tells the forge where to send
  deliveries.
- Polling: asking the forge what has changed, for a server the forge
  cannot reach with deliveries. The poller turns what it finds into
  deliveries, so the rest of the system sees no difference.
- Snapshot: a copy of a pull request as it was at one moment: its title,
  description, commits and changed files.
- Observation: taking a snapshot of a pull request, storing it, and
  recording that it was taken.
- Evaluation: reviewing a pull request against an organisation's
  policies. This context starts evaluations. It does not carry them out.
"""
