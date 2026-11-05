# ADR 009: The review comment is written by an editor from the server's draft

## Status

Proposed, 2026-11-05.

## Context

A review comment is assembled from findings. Each finding is one
folded line naming the clause it breaks and where, and under the fold
the passage quoted and what the judge said is wrong with it. Every
finding is shown at the same weight, in the order the policies answered.
On a pull request of the GoSource web site the two gnomes raised
twenty-six findings. Half of pr-gnome's were noise: a quoted heading
judged as the author's register, two findings whose own reason said the
passage complied, a garden path the judge conceded resolves. The author
would have read a list and learned to skip it.

What makes a review comment land is known. A good maintainer writes one
to four sentences a point, says the consequence and not the rule, gives
the alternative with the objection, marks what does not block, asks
when unsure, and never writes about the person. Authors rate findings
of defects useful and praise and hedged questions not. A bot's comment
is resented for its length, its frequency, and for repeating what the
thread already holds. The purpose of mechanising the obvious feedback
is to spare a skilled reviewer's time for taste, judgement and
architecture, and a comment the author skips spares nothing.

## Decision

A binding may carry an editor: `pr-comment-editor.md`, the instructions
a model follows and the class of model, and `pr-comment-editor/examples/`,
comments named good or bad, each with one line on why. The binding
holds them because one editor speaks for every reviewer on a server,
and because what a good comment is belongs with whoever decides what
an organisation is reviewed for.

With an editor in force, the comment the author reads is the editor's.
The server assembles the draft as before, every reviewer's part, and
gives the editor the draft without the markers the server reads, the
pull request's title and its description. What comes back is posted
under the evaluation's marker. The findings are unchanged: they stay in
the journal, the commit statuses count them, and what stands or is
fixed is still read from them. A "comment edited" fact keeps the draft
and what was posted, the model, and the reviewers whose parts the draft
held, so that what the editor dropped can be read later.

A finding names its clause as a link to the clause's page on the
gnome's site, and the author should be able to read the rule and argue
with it where it is kept. The server counts the links the draft held
and how many the posted text kept, on the fact. A link the draft did
not hold leads the author somewhere nothing vouches for, so a comment
carrying one is not posted: the draft is, and the fact says which link.

The editor writes at observe too, where nothing is posted, and the fact
is recorded, so a binding's editor can be read against real pull
requests before a gnome is set to advise. An editor that refuses or
cannot answer does not lose the review: the draft is posted as it was,
and the fact says why. The editor's calls are recorded as every call
to a model is, so what it costs is added up with the judge's.

The editor sees the title and the description and nothing else of the
pull request. They are small and of one shape for every gnome, and the
description is where a quoted heading is misread. For a gnome that
judges code or pages, the editor sees only what the findings quote.
What else it should be shown, a diff, a page, is an open question this
record does not settle.

## Consequences

- A server without an editor in force posts the draft, as before.
- The comment the author reads no longer carries each reviewer's
  marker inside it. Nothing reads those; reactions at close are
  collected by comment id.
- The examples are the editor's cases. When a comment lands badly, the
  comment and why go in as a bad example in the binding, and the next
  comment is written against it. Whether an editor keeps or drops
  truly is read from the fact, which is where its calibration begins.
- One more model call per evaluation that has something to say, of
  the editor's class.
