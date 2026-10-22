# Restic: repository cannot be opened after a failed format upgrade

This is a constructed benchmark scenario, not a verified customer incident.

A previously working backup repository is stored on a local filesystem. An
attempt to upgrade its format fails with a storage write error. Afterwards,
commands that normally open the repository report that its configuration file
is missing. The original backup data is still present.

Investigate how this can happen. Implement a repair that preserves a working
repository where possible when the operation fails, and verify the relevant
behavior and package tests. Report any existing recovery mechanism as well as
the limits of your repair.
