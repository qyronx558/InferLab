# Workflows

`ci.yml` checks pull requests, pushes to main and manual runs on a standard Ubuntu
CPU runner. It installs from lockfiles, checks formatting/lint/types, builds the
frontend, runs unit tests, and checks the optional hook configuration/private keys.
It has read-only repository permission, a 15-minute timeout and no deployment,
model downloads, GPU access or repository secrets. Actions are pinned by commit.

Run `scripts/check.ps1` locally and `uv run --locked pre-commit run --all-files`
for the corresponding checks. Full secret-scanning guidance is in
`CONTRIBUTING.md`; the private-key hook does not detect every credential type.
