# What a review says, and where each part comes from

For the author of a pull request a server has reviewed, and for
whoever keeps the binding that server judges by. [What is deployed
where](architecture.md) explains the services that do the work;
[what a gnome is](gnomes.md) explains the rules; [words](words.md)
gives each word one line.

## What appears on the pull request

About a minute after the last push, the server writes three things on
the pull request, one set for each reviewer the binding declares for
the repository:

- a comment, one folded line per finding naming the clause it breaks,
  linked to the clause's page on the gnome's site, and where; unfolded,
  the words at fault and what is wrong with them;
- a label, with the reviewer's verdict;
- a commit status named by the reviewer's id, `pass`, `warn` or
  `fail`.

A push that follows within the repository's boundary, 60 seconds in
the examples, joins the same review.

## Where each part comes from

Every part of the comment is one file of the binding, and the binding
holds a copy of each gnome at one commit.

| Part | File | What it is |
|---|---|---|
| The clause a finding names | `<reviewer>/doctrine/*.md` | One clause of the doctrine, by its id and name |
| Where the clause's name links to | `<reviewer>/manifest.md` | Its `site` line, the address the gnome publishes its pages at |
| The finding | `<reviewer>/policies/<ID>-<name>.md` | The policy whose question the judge answered. Its header lists the clauses it may cite |
| The grade | The same policy | Its instructions say what earns `warn` and what earns `fail`, and its `ceiling` caps the worst |
| The words quoted | The pull request | The part the policy's `evidence` line names: the title, the description, the commits or the patches |
| That the policy ran at all | `declarations.toml` | The line that turns this policy on for this repository |
| The example the judge was measured on | `<reviewer>/cases/<ID>/*.md` | A clean case, with nothing wrong, or a seeded case, with one fault and the clause a correct judge reports |

## One finding, end to end

[bugflow-examples](https://github.com/bugflow/bugflow-examples) holds
a gnome for kernel-style pull requests. Its seeded case
`narrative/cases/ED-01/seeded-01-marketing.md` is a description that
begins:

> This adds a powerful, seamless poller that lets developers leverage
> the ingress from a laptop.

The case's header says what a correct judge reports: `expect:
VOICE-6`, `grade: fail`. Traced back:

1. `VOICE-6`, marketing register, is a clause of
   `narrative/doctrine/01-editorial-voice.md`. Its name is the heading
   the comment shows.
2. `ED-01`, in `narrative/policies/ED-01-editorial-voice.md`, is the
   policy that lists `VOICE-6` among the clauses it judges. Its
   `evidence` line is `description`, so the judge read the description
   and nothing else. Its instructions say what a marketing register
   is and what grade it earns.
3. `declarations.toml` in the binding names `ED-01` for the
   repository, which is why the judge was asked.
4. A calibration runs `ED-01` over every case in `cases/ED-01/` and
   counts the cases the judge answered as their headers say. The
   counts are in the policy's notes below `=== calibration`.

## What to do with a finding

- **It is right.** Change the words and push. The next review reads
  the new words.
- **It is wrong.** The judge is a model, and it is wrong sometimes.
  Whoever keeps the binding answers: a clean case with the disputed
  words goes into the gnome, so that the next calibration counts the
  mistake, and the policy's instructions change if the mistake
  repeats. The finding is not edited away on the pull request.
- **It is right, but the rule is wrong.** The clause is changed in the
  gnome, by pull request there, and every policy that lists it is
  measured again.

What a finding does to a merge, whether a `fail` blocks it, is the
operator's declaration for the repository, not the gnome's.
