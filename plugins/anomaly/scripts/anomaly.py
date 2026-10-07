"""Entry point: python anomaly.py <command> ... (see anomaly_loop/cli.py)."""
import sys
from pathlib import Path


def run():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from anomaly_loop import cli
    sys.stdout.reconfigure(encoding='utf-8')
    return cli.main()


if __name__ == '__main__':
    sys.exit(run())
