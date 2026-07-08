"""press — the template-press command line.

Noun-verb dispatcher (design 0006): `press rebrand --target …` presses an
identity onto an external target repo. `provision` and `status` are reserved
for the M6 Provision phase and currently exit 2 with a pointer.
"""

from __future__ import annotations

import sys

from template_press.rebrand import cli as rebrand_cli

_RESERVED = {"provision", "status"}

_USAGE = """\
usage: press <command> [options]

commands:
  rebrand    press an identity onto a target repo (press rebrand --help)
  provision  configure a target's features (coming in M6)
  status     report a target's provisioned state (coming in M6)
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    verb, rest = args[0], args[1:]
    if verb == "rebrand":
        return rebrand_cli.main(rest)
    if verb in _RESERVED:
        print(
            f"error: '{verb}' is part of the Provision phase and is not "
            f"available yet (coming in M6).",
            file=sys.stderr,
        )
        return 2
    print(f"error: unknown command {verb!r}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
