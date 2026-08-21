"""Allow ``python -m jobnotify ...`` as an alias for the ``jobnotify`` script."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
