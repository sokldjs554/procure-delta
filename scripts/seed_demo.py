from pathlib import Path
import sys


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
    from app.demo.seed import main as seed_main
    seed_main()


if __name__ == '__main__':
    main()
