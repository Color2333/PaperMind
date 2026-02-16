from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.storage.db import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("SQLite schema initialized.")


if __name__ == "__main__":
    main()
