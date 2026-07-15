import argparse
import json

from .aggregator import Aggregator
from .config import Config
from .lark_client import LarkClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry_run", "commit"], default="dry_run")
    args = parser.parse_args()

    cfg = Config()
    cfg.validate()
    result = Aggregator(cfg, LarkClient(cfg.feishu_app_id, cfg.feishu_app_secret)).run(args.mode)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
