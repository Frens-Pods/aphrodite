# Private overlay

The public repository is designed to run from tracked files only. Operator-private material belongs outside the public tree, under the gitignored overlay directory:

```text
.local/advena/
```

The overlay mirrors repository structure when preservation is useful, for example:

```text
.local/advena/aphrodite/
.local/advena/tests/
.local/advena/docs/
.local/advena/scripts/
.local/advena/config/
.local/advena/systemd/
.local/advena/caddy/
```

## What belongs in the overlay

Keep these out of tracked files:

- Real `config/aphrodite.env` values.
- Real Discord bot tokens, public keys, channel IDs, user IDs, and role IDs.
- Absolute local deployment paths.
- Host-specific service manager and reverse proxy files.
- Operator activation/cutover runbooks, approval notes, evidence exports, and local incident records.
- Hermes-plugin adapter modules relocated out of the public module set:
  `nudge`, `readsurface`, `soulglass`, `kanban`, and `nixie`, together with
  their dedicated tests and documentation.
- Any private notes that name a specific deployment, operator, workstation, or Discord server.

The public repository should contain only generic `.example` templates and reusable source code.

## Local configuration

Start from the public environment template:

```sh
cp config/aphrodite.env.example config/aphrodite.env
```

Then edit `config/aphrodite.env` locally. Do not commit it. If a deployment needs a preserved private copy, store it under the overlay, for example:

```text
.local/advena/config/aphrodite.env
```

## Fresh-clone rule

A fresh clone of the public repository must be able to install, import, run its public tests, and serve the public FastAPI app without `.local/advena/`.

The overlay is preservation and operator material only. Public code must not import from it, tests must not depend on it, and documentation should explain how to create new local configuration from `.example` files rather than requiring private files.
