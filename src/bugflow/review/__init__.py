"""The review context: reviewing a pull request against written rules,
and publishing what was found.

Words used throughout:

- Doctrine: a document of numbered rules about how something should be
  written or built. Each rule is a clause, with an id such as "RULE-3".
- Policy: one thing a pull request is checked for, with an id of its
  own. A policy rests on one or more clauses.
- Judge: a language model asked whether a pull request breaks a policy.
  A policy answered this way is a judged policy.
- Checked policy: a policy that a function answers, with no model.
- Finding: one policy's verdict about one thing in a pull request, such
  as a commit message. It has a severity: "info", "warn" or "fail".
- Reviewer, or review agent: a named set of policies, doctrine and
  instructions that is installed on a server. It has an agent id.
- Checkout agent: a reviewer that reads the repository's files, by
  running as a task on a runner. It answers with a write-up.
- Write-up: the prose a checkout agent wrote about a commit.
- Grader: a language model that reads a write-up and says which verdict
  it supports.
- Verdict: one reviewer's result for one commit: "pass", "warn" or
  "fail".
- Evaluation: one run of the review of one pull request, from reading
  it to publishing. An evaluation is one workflow run.
- Corpus: the doctrine and the judge's settings that an evaluation runs
  under. Its version changes when either changes, so a finding can say
  which rules it was raised under.
- Submission: the parts of a pull request that a policy reads: title,
  description, commits and changed files.
- Stocktake: a review that runs on a schedule and covers everything
  merged since the last one, where an evaluation covers one pull
  request.

This context does not fetch pull requests or run agents. It declares
interfaces for both, and an application supplies them.
"""
