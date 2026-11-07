# ADR 009: A server signs in to GitHub as a GitHub App

## Status

Proposed, 2026-11-07.

## Context

A server signs in to GitHub with a personal access token, one for any
owner or one for each owner (`FORGE_TOKEN`, `FORGE_TOKENS_BY_OWNER`).
A personal access token acts as the person who minted it, so every
comment, label and status the server writes is attributed to that
person, and the person's own repository rights bound what the server
may do. When the person leaves an organisation, or the token is
revoked, the server stops. An installer who wants the server to post
under its own name has to create a second GitHub account for it, seat
it in the organisation, and keep its sign-in.

GitHub offers an identity made for this. A GitHub App is registered
once, installed on an organisation or on chosen repositories by an
owner of theirs, and granted permissions of its own. It has no token:
it holds a private key, signs a short-lived JWT naming itself, and
exchanges that for an installation access token that lasts an hour.
GitHub attributes what the token does to the App's bot, `name[bot]`,
and gives the App rate limits of its own.

## Decision

A server may sign in to GitHub as a GitHub App. The App is named by
its id, its private key and the installation on each owner it is
installed on (`FORGE_APP_ID`, `FORGE_APP_PRIVATE_KEY` or
`FORGE_APP_PRIVATE_KEY_FILE`, `FORGE_APP_INSTALLATIONS`). The forge
adapter mints an installation token for an owner when first asked
for one and again when fewer than five minutes of its hour remain,
and signs each request to that owner's repositories with it.

The tokens stay. An owner's own token in `FORGE_TOKENS_BY_OWNER` is
used before the App's, and `FORGE_TOKEN` where neither names the
owner, so a server moves from a token to an App one owner at a time,
and a Forgejo, which has no Apps, is reached as before.

The installations are named, not discovered. Listing them would cost a
request at start and make the set of owners implicit in what GitHub
holds; naming them keeps the owners a server acts for in its settings,
beside the tokens by owner, in the same shape.

Discovery lists the owners the App is installed on as it lists those
with a token of their own. The runner's read-only repository token
(`REVIEW_REPOSITORY_TOKEN`) is unchanged: a session mounts a
repository with it, and it is never the server's credential.

## Consequences

An installer registers one App for each server and installs it where
the server is to act. The App's repository permissions are those the
token needed: Contents read, Pull requests write, Issues write for
labels, Commit statuses write, Webhooks write for `bugflow webhooks`,
and Metadata read, which GitHub grants every App.

A server whose private key is stolen can be stopped by generating a
new key at GitHub, which revokes the old one; a token had to be
revoked where it was minted.

A deployment carries the private key as a secret and writes it into a
setting with each line break as `\n`, since a settings file holds one
line a value; the program reads either form, or a file.
