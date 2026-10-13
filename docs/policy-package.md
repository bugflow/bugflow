# The policy package

What a server reads when a repository of policies is deployed to it, and
what else such a repository holds for other readers. This is the
specification; the parsers in `src/bugflow/method/infrastructure/` and
`src/bugflow/apps/worker/litellm_judge.py` implement it, and a policy
repository's own tests check its files against it.

A policy package is a directory. The files in it are of two kinds: a
gnome, which is one doctrine with its policies and cases and is the same
wherever it is used; and a binding, which says what the gnome applies to
on one server. A repository may hold one gnome, several, or a binding
and the gnomes it pins.

## Layout

    pace-layers.toml            binding: the processes and when they run
    declarations.toml           binding: what each repository is reviewed for
    <reviewer>/manifest.md      gnome: the reviewer's id, subjects, policies, checks
    <reviewer>/doctrine/*.md    gnome: the doctrine, read in filename order
    <reviewer>/policies/*.md    gnome: one policy each
    <reviewer>/cases/<ID>/*.md  gnome: the cases of policy <ID>; not sent
    <reviewer>/bin/, lib/       gnome: checks a garden's lint runs; not sent
    <reviewer>/skills/          gnome: skills a garden installs; not sent

A server reads the two binding files and, of each reviewer, the manifest,
the doctrine and the policies. A deployment holding a file of any other
path is refused. `bugflow deploy-policies DIRECTORY` sends only the files
a server reads, so a repository holds its cases, checks, skills, notes
and pipeline beside them.

`reviewer.md` is read as `manifest.md` is, for repositories made before
the manifest had that name.

## The manifest

A header, a line of three dashes, and prose for a person, which the
server does not read:

    agent_id: narrative
    summary: What a change says about itself
    subjects: pull-request/description, pull-request/commits
    policies: CM-01, ED-01
    checks: em-dash ED-04 VOICE-21
    ---
    Prose.

- `agent_id`: the reviewer's id. The commit status on a pull request has
  this name. Required.
- `summary`: one line. Required.
- `subjects`: the subjects the reviewer's policies read, comma-separated.
  Optional; a server does not read it.
- `policies`: every policy of the reviewer, by id, comma-separated.
  Optional; absent, the reviewer is its prose alone.
- `checks`: each policy that code answers rather than a model: the
  check's name, the policy's id and the clause its findings cite, as three
  words, entries comma-separated. A policy on this line need not have a
  file. A server has a fixed set of checks, and a manifest naming one it
  lacks is refused when the server knows its checks.
- `runner`: `judge` for a reviewer that is its policies, or the name of a
  runner for an agent that checks the code out. Optional; absent,
  `judge`.
- `governs`: `yes` when the reviewer's verdict decides a pull request's
  label. Optional; absent, `yes`.

A header line of any other key is a problem in `reviewer.md` and ignored
in `manifest.md`, so that a gnome may say more about itself than a
server reads.

## A policy file

A header, a line of three dashes, the instructions, a line
`=== calibration`, and the calibration notes. The filename opens with the
policy's id.

    policy_id: ED-01
    subject: description
    summary: The title and description are plain and factual
    model_class: medium
    evidence: pull-request/description
    quotable_name: title or description
    graded: yes
    quotes_code: no
    clause: VOICE-6 marketing register
    ---
    What the model is told.
    === calibration
    What measuring it has shown.

- `policy_id`, `subject`, `summary`: as the manifest's words say.
- `model_class`: the class of model the policy needs, `small`, `medium` or
  `large`; or `none` for a policy a check answers.
- `evidence`: the subject the model is shown, below. The kind alone,
  `description`, names the pull request subject of that kind.
- `quotable_name`: the name, in the server's words, of the text a finding
  may quote from. A quote from anywhere else is discarded.
- `graded`: `yes` when the model is asked a grade for each finding.
- `quotes_code`: `yes` when a quote may come from code.
- `ceiling`: the worst grade a finding may carry, `warn` or `fail`;
  absent, `fail`.
- `implemented`: `judge` or `check`; absent, `judge`. A checked policy's
  instructions are for a person: the server runs the check its manifest
  names, and the policy's `model_class` is `none`. A checked policy whose
  check the server lacks is parsed and never declared: a declaration
  naming it is refused.
- `clause`: one clause the policy judges, its id and the name the policy
  gives it. It repeats.

The instructions are given to the model after the doctrine. Lines are
wrapped for reading; a line that does not open a list item continues the
line above. Nothing below the calibration line reaches the model, so a
measurement written down does not change the fingerprint it was taken
under.

## Subjects

A subject names the evidence a policy reads, as `KIND/PART`. A server
renders the subjects it has code for, and a declaration naming a policy
whose subject it does not render is refused; so a gnome may hold a
policy for one consumer that another skips.

| Subject | What the model is shown | What a quote must come from |
|---|---|---|
| `pull-request/description` | the title and the description | the same |
| `pull-request/commits` | each commit's message | each commit's summary |
| `pull-request/scope` | the title, the description, the commit messages and each changed file's path with its line counts | the same, without the counts |
| `pull-request/patches` | all of that and each file's patch | the same, patches included |
| `document/file` | each document the pull request changes, as the patch shows it after the change: the added and kept lines of each hunk, in order, with a line saying which parts are shown | the same |
| `scope/canon` | every document of a scope | not rendered by a pull request judge |

A document is a file whose name ends in `.org` or `.md`. A pull request
that changes none has nothing for a `document/file` policy to read, and
the policy reports nothing.

## The doctrine

The files of `doctrine/`, each Markdown, joined in filename order into
one document. A clause is a paragraph opening `**ID. Name.**`, such as
`**VOICE-6. Marketing register.**`. A finding cites a clause id, and a
policy may cite only the clauses its header lists.

## A case

Cases are a gnome's tests of its judge. A server does not read them; a
calibration does. A case is a header, a line of three dashes, and the
evidence in its subject's form:

    title: Retry the judge on a timeout
    expect: GIT-4
    grade: fail
    why: The body names a second change with a reason of its own.
    ---
    <the evidence>

- `title`: the pull request's title, or the case's.
- `expect`: the clause a correct judge reports. Empty in a clean case.
  `A, B` expects both; `A | B` accepts either.
- `grade`: the grade a correct judge gives, in a seeded case of a graded
  policy.
- `why`: the reason for the case's label, in one sentence. The judge is
  not shown it.

For a pull request subject the header also carries `commit` lines, each
a commit's summary with the lines after it that open with `|` the rest
of its message, and `file` lines, each a changed file's path and line
counts; the body is the description, then `=== patch <path>` blocks. For
`document/file` the header carries `path`, the document's path, and the
body is the document.

A case is named `clean-NN-name.md` when a correct judge reports nothing
and `seeded-NN-name.md` when it reports one finding.

## The binding

`pace-layers.toml` declares each process the server runs for a
repository and the layer that gives it its cadence:

    [process.evaluate-pull-request]
    subject = "pull request"
    judges = true

    [layer.pull-request]
    cadence = "event"
    processes = ["evaluate-pull-request"]

`declarations.toml` has one table for each repository, naming the
policies judged and the processes dispatched:

    [repository."owner/name"]
    policies = ["CM-01", "ED-01"]
    processes = ["evaluate-pull-request"]

The key is `owner/name` for a repository on GitHub, or `forge:owner/name`.
A policy must be one the deployment holds, by a file or a manifest's
`checks` line, with a subject the server renders and, for a checked
policy, a check the server has. A repository the file leaves out is
reviewed for nothing once the file is deployed.

## Deployment

A deployment is one commit of the repository, sent whole through
`POST /api/policy-deployments` by `bugflow deploy-policies` from the
repository's own pipeline, or installed on the host by `bugflow
install-policies`. Every problem in it is reported at once. With
`--check` the server parses and stores nothing. `docs/deploying.md` says
how a pipeline signs in.
