#!/usr/bin/env python3
"""Manage Arena RTMP web users without exposing password hashes."""

import argparse
import getpass
import json
import sys

try:
    from app.access_control import ROLES, UserStore, UserStoreError
    from app.settings import SETTINGS
except ImportError:
    from access_control import ROLES, UserStore, UserStoreError
    from settings import SETTINGS


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("set", help="create or replace a user")
    add.add_argument("username")
    add.add_argument("--role", required=True, choices=ROLES)
    add.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from stdin",
    )

    disable = subparsers.add_parser("disable", help="disable a user")
    disable.add_argument("username")

    subparsers.add_parser("list", help="list users without password hashes")
    return parser


def read_password(password_stdin):
    if password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise UserStoreError("Passwords do not match")
    return first


def main():
    arguments = build_parser().parse_args()
    store = UserStore(SETTINGS.users_file)

    try:
        if arguments.command == "set":
            store.set_user(
                arguments.username,
                read_password(arguments.password_stdin),
                arguments.role,
            )
            print(f"User {arguments.username!r} saved as {arguments.role}.")
        elif arguments.command == "disable":
            store.disable_user(arguments.username)
            print(f"User {arguments.username!r} disabled.")
        else:
            print(json.dumps(
                store.public_users(),
                ensure_ascii=False,
                indent=2,
            ))
    except UserStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
