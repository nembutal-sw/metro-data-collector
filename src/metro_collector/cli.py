from __future__ import annotations

import argparse
import asyncio
import json

from metro_collector.collectors.seoul_open_data import SeoulOpenDataCollector
from metro_collector.config import get_settings
from metro_collector.db import Database
from metro_collector.logging import configure_logging
from metro_collector.worker import SyncWorker


async def _run_worker() -> None:
    settings = get_settings()
    settings.ensure_data_directories()
    database = Database(settings.database_url.get_secret_value())
    await database.open()
    try:
        await SyncWorker(settings, database).run_forever()
    finally:
        await database.close()


async def _inspect() -> None:
    metadata = await SeoulOpenDataCollector(get_settings()).inspect()
    print(
        json.dumps(
            {
                "code": metadata.code,
                "name": metadata.name,
                "kind": metadata.kind,
                "coverage": metadata.coverage,
                "access_status": metadata.access_status,
                "base_url": metadata.base_url,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="metro-sync")
    parser.add_argument("command", choices=("worker", "inspect"))
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    if args.command == "worker":
        asyncio.run(_run_worker())
    else:
        asyncio.run(_inspect())


if __name__ == "__main__":
    main()
