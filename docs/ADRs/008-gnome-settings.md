# ADR 008: Each gnome is set for each repository by a behaviour and a profile

## Status

Proposed, 2026-10-27. Amended, 2026-10-27: a command makes the
settings from the declarations, and the change is released in two
steps; the label is decided by the gnomes that publish where none
gates, and by every gnome that judges where none publishes; a process
that names a reviewer runs where that gnome judges.

## Context

Four records decide what a server does with a repository, and each is
kept in a different place:

- the repositories watched, in `WATCHED_REPOSITORIES`, set when the
  server is deployed;
- whether findings reach the forge and which verdict fails a status,
  in the enforcement profile bound to the repository, written on the
  host by `bugflow declare --profile`;
- which reviewers decide the label, in `review_governance`, which
  nothing writes;
- which policies judge the repository, in the binding's
  `declarations.toml`, deployed by the binding's pipeline.

A repository created in an organisation is reviewed only after a
change to the deployment's settings, a redeploy, a command on the
host and a pull request to the binding. A repository's reviewers
cannot be judged at different strengths, because the enforcement
profile holds for every reviewer.

## Decision

An operator sets each gnome for each repository by two values, a
behaviour and a profile. The behaviour says what the gnome may do. The
profile says what it judges. Behaviours are stored in the server's
database and changed often. Profiles are stored in the binding and
changed by pull request, because they change what people are judged
on.

### The behaviour

A behaviour is one of four, each including the one before:

| Behaviour | What the gnome does |
|---|---|
| `off` | Judges nothing |
| `observe` | Judges, and journals its findings. Nothing reaches the forge |
| `advise` | Also posts its comment and its commit status. The status never fails |
| `gate` | Also fails its status on a `fail` verdict |

A repository and gnome with no setting are `off`.

The label is written while any gnome on the repository publishes. The
gnomes at `gate` decide it where any gates. Where none does, the gnomes
at `advise` decide it, so an advised repository's label is advice and a
gnome at `observe` never moves a label the forge shows. Where none
publishes, every gnome that judges decides it, so an observed
repository's journal records the label it would have.

### The profile

A profile is a named set of one gnome's policies. The binding defines
them in `profiles.toml`:

    [profile.pr-gnome.default]
    policies = ["CM-01", "CM-02", "ED-01", "ED-02", "ED-03", "ED-04",
                "ED-05", "PR-04", "SC-01", "SC-02"]

A gnome the file names no profile for has one, `default`, which holds
every policy of the gnome that the server answers. A binding with one
profile for each gnome is configured by behaviour alone, and a page
or command offers no choice of profile.

A deployment is refused if it drops a profile that a setting names,
or if a profile names a policy that its gnome does not have.

### The setting

A setting is a row for one repository and one gnome:

    forge, repo, gnome, behaviour, profile, set_by, set_at

`bugflow set` writes it on the host, and the API writes it for an
operator who holds the server's settings role. Each change is a fact
in the journal, saying who made it.

### What follows from the settings

- **Watching.** A repository is watched while any of its gnomes is
  above `off`. The poller, the worker's schedules and the webhooks
  read the settings, not `WATCHED_REPOSITORIES`. The webhook is made
  when the first gnome leaves `off` and removed when the last returns
  to it.
- **Boundaries.** A layer in `pace-layers.toml` may give a
  `default_boundary`. A watched repository with no boundary on a layer
  takes it. The worker stops only for a watched repository with no
  boundary on a layer that has no default.
- **Processes.** A process that names a reviewer runs on a repository
  where that reviewer's gnome judges. A process that names none runs
  for every watched repository. A repository no longer names its
  processes.
- **Withholding.** The share of warnings withheld remains a setting of
  the repository.

### Discovery

The worker runs a schedule that lists the repositories of each owner
it holds a forge token for. A repository found for the first time is
recorded with every gnome `off`. A renamed repository resolves to its
existing row under ADR 005, and the rename is recorded. An archived
repository is recorded as archived, and its gnomes are set to `off`.

### Words

"Profile" means a set of policies and nothing else. What the
enforcement profile was is the behaviour: `EnforcementProfile`,
`ProfileName` and `bugflow declare --profile` are renamed for it, and
`docs/words.md` defines both words.

### The change from declarations

`declarations.toml` is retired, in two releases.

The first release parses `profiles.toml` and keeps the settings, and
nothing reads them yet. A server that has not taken it refuses a
deployment that carries `profiles.toml`, so each binding adds its
profiles after its server takes the release.

Then `bugflow settle` makes the settings from each repository's
declarations, enforcement profile and governance rows:

- each gnome with a policy declared takes the profile whose policies
  are exactly those declared, `default` first;
- its behaviour is the enforcement profile's, except that `gate` is
  `advise` for a gnome that did not govern the label, since its
  status never failed.

It is a command and not a script, because which profile a
repository's declared policies are is known only by parsing the
deployment in force, and a script does not import the package (ADR
004). A repository whose declared policies for a gnome match no
profile stops it, and nothing is written, so that no setting is made
by guess. The operator deploys a profile that matches and settles
again. A setting already made is left as it is.

The second release reads the settings. It refuses a deployment that
carries `declarations.toml`, drops the declaration, enforcement and
governance tables, and each binding removes the file in the same step.

## Rules

1. One setting for each repository and gnome: a behaviour and a
   profile.
2. Profiles are deployed from the binding. Behaviours are set in the
   server.
3. A repository is watched while any of its gnomes is above `off`.
4. A deployment may not drop a profile that a setting names.
5. A discovered repository starts with every gnome `off`.

## Consequences

A repository created in an organisation can be reviewed by setting
one gnome above `off`, with no deployment and no pull request.

A gnome can be tried on a repository at `observe` while another gnome
posts there at `advise`.

The policies a repository is judged on are still reviewed before they
take effect, because they are chosen from profiles that only the
binding defines.

The manifest's `governs` flag no longer chooses the gnomes that
decide a label, since the settings do. It says which gnomes may: one
that gives no verdict on a pull request's head, as one only a
stocktake runs, says `no`, and is left out of the label at any
behaviour, which would otherwise hold it at work in progress.

A behaviour for each organisation, given to the repositories that
discovery finds, is left for later. Discovery records repositories
`off` until someone decides otherwise.
