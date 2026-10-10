"""The method context: the policies a server reviews with, and how they
reach it.

Words used throughout:

- Policy repository: a repository an organisation keeps its reviewers,
  policies and doctrine in. Its layout is one directory for each
  reviewer.
- Deployment: the files one commit of a policy repository sent to a
  server. A server fetches nothing from a policy repository. The
  repository's pipeline sends the files.
- In force: the deployment a server reviews with now.
"""
