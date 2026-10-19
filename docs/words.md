# Words

What bugflow calls things, one line each, and where each is defined.
The line is a reminder, not the definition: read the document it
names. [What a gnome is](gnomes.md) explains a gnome's parts for a
maintainer, [the policy package](policy-package.md) specifies each
file, and [what is deployed where](architecture.md) explains a server.

The words of a tree of responsibilities, a methodology and the image
that installs one are ClankOS's, printed by `clankos-run help words`
and kept at
<https://github.com/ClankaOperatingSystem/clankos/blob/master/docs/words.txt>.
A skill folder is the agentskills.io format: <https://agentskills.io>.

## A gnome and its parts

- **Gnome.** A repository that holds an editorial standard for one
  kind of thing and the means to keep to it. To a garden it is a
  methodology: a skills repository with checks, and the doctrine,
  policies and cases besides. [What a gnome is](gnomes.md).
- **Doctrine.** The standard, written for a person, as a list of
  clauses; the files of `doctrine/` read in filename order as one
  document. [What a gnome is](gnomes.md), "The definition".
- **Clause.** One rule of a doctrine, with an id never reused, such as
  `VOICE-6`, and a name. [What a gnome is](gnomes.md).
- **Policy.** One question asked about a subject, and the clauses it
  judges; one file of `policies/`, with an id such as `ED-01`.
  [The policy package](policy-package.md), "A policy file".
- **Subject.** What a policy reads, named on its `evidence` line: a
  part of a pull request, one document, or every document of a scope.
  [The policy package](policy-package.md), "Subjects".
- **Case.** An example stored with the answer a correct judge gives
  it. A clean case has nothing wrong; a seeded case has one fault
  written in. [What a gnome is](gnomes.md), "Add a case".
- **Check.** A script in a skill's `scripts/`, `check-<name>`, that
  answers a policy in code; a garden's lint runs it. A server's checks
  are its own code, given a policy by the manifest's `checks` line.
  [What a gnome is](gnomes.md), "What a server makes of a gnome".
- **Skill.** ClankOS's word, in its
  [words](https://github.com/ClankaOperatingSystem/clankos/blob/master/docs/words.txt).
  A gnome's skill, `skills/<skill>/`, holds a copy of the doctrine and
  the policies in its `references/`. [What a gnome is](gnomes.md).
- **Manifest.** `manifest.md`: the gnome's id and the lists of its
  subjects, policies and checks. [The policy package](policy-package.md),
  "The manifest".
- **Calibration.** One run of a policy over all of its cases, counting
  the cases the judge answered correctly, recorded in the policy's
  notes below `=== calibration`. [What a gnome is](gnomes.md),
  "Measure a policy".

## A server and what it says

- **Server.** One running composition of bugflow: the API, the
  worker, the ingress and their database, judging pull requests by the
  deployment in force. [What is deployed where](architecture.md).
- **Reviewer.** What a server calls a gnome's directory in a
  deployment: a manifest, policies and a doctrine, whose findings make
  one verdict, named by the manifest's `agent_id`. Not a process:
  nothing runs under a reviewer's name. [What a gnome is](gnomes.md), "What a server makes of
  a gnome".
- **Judge.** The model, when it answers one policy for one subject,
  with the doctrine of the reviewer that holds the policy. Code in the
  worker, not a reviewer or a service of its own.
  [What is deployed where](architecture.md), "How a pull request is
  reviewed".
- **Checkout agent.** A session on a vendor's platform that checks the
  code out and writes a review, for a reviewer whose manifest names a
  runner other than `judge`. Not part of the composition.
  [What is deployed where](architecture.md), "How a pull request is
  reviewed".
- **Model class.** `small`, `medium` or `large`: the class a policy
  names, which each server fills with a model of its own choosing.
  [The policy package](policy-package.md), "A policy file".
- **Finding.** One thing a judge or a check reports against a
  subject: the words at fault and one clause. [What a gnome is](gnomes.md),
  "How the parts relate".
- **Grade.** How bad a finding is, `warn` or `fail`. A policy's
  `ceiling` is the worst grade its findings may carry.
  [The policy package](policy-package.md), "A policy file".
- **Ceiling.** The worst grade a policy's findings may carry, `warn`
  or `fail`, named in its header; a policy that names none may fail.
  [The policy package](policy-package.md), "A policy file".
- **Verdict.** A reviewer's result for one commit, `pass`, `warn` or
  `fail`: the worst grade among its findings. The reviewer's commit
  status is set from the findings. [What a gnome is](gnomes.md), "What a server makes of a
  gnome".

## How rules reach a server

- **Binding.** A repository that says which gnomes, at which commits,
  apply to which repositories under review, in `declarations.toml`,
  and when the server's processes run, in `pace-layers.toml`; it holds
  a copy of each gnome it pins. [What is deployed where](architecture.md),
  "Three kinds of repository".
- **Declaration.** A line of `declarations.toml`: one policy turned on
  for one repository. [The policy package](policy-package.md), "The
  binding".
- **Glossary.** The words documents of ClankOS and bugflow, copied into
  a binding under `glossary/` and sent with its deployment; a policy
  whose subject is `document/glossary` reads them.
  [The policy package](policy-package.md), "Subjects".
- **Pace layer.** A group of the server's processes that run at one
  cadence, on an event or on a clock, declared in `pace-layers.toml`.
  [The policy package](policy-package.md), "The binding".
- **Deployment.** Two things. A policy deployment is the files of one
  commit of a binding, stored in the database, which a server judges
  by; the one in force is the latest sent. A deployment of the server
  is the composition and settings of one server, which
  [Deploying a server](deploying.md) covers. [What is deployed
  where](architecture.md), "How rules reach a server".
- **Operator.** Whoever runs a server: declares its repositories,
  fills its model classes, and says whether findings are published.
  [What is deployed where](architecture.md).
