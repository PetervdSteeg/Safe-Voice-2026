"""Send stored records through the pipeline again, for example after the mapping or the CDM changed.

    python -m ui.resync                     all records of all users
    python -m ui.resync --user alice        one user
    python -m ui.resync --only-unsynced     only records that are not in the database yet

The uploads add triples to the user's graph. To replace old data: python -m src.storage.admin drop-user alice
first. The SQLite database stays the source of truth.
"""
import sys

from ui import store


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    user = argv[argv.index("--user") + 1] if "--user" in argv else None
    synced, failed = store.resync_all(user, only_unsynced="--only-unsynced" in argv)
    print(f"Sent again: {synced} in the database, {failed} failed (see data/audit/audit.log for the reasons).")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
