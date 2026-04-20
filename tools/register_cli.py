import os
import sys
import argparse
import asyncio
import logging

# 设置路劲以加载 backend 模块
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from backend.core.config import settings
from backend.core.database import AsyncJsonDB
from backend.core.account_pool import AccountPool
from backend.services.register import perform_batch_registration

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("register_cli")

async def main():
    parser = argparse.ArgumentParser(description="Qwen Account Batch Register CLI")
    parser.add_argument("--count", type=int, default=1, help="Number of accounts to register")
    parser.add_argument("--threads", type=int, default=4, help="Number of concurrent threads")
    args = parser.parse_args()

    # 初始化数据库和账号池
    log.info(f"Loading accounts from {settings.ACCOUNTS_FILE}...")
    db = AsyncJsonDB(settings.ACCOUNTS_FILE, default_data=[])
    pool = AccountPool(db)
    await pool.load()

    # 执行批量注册
    log.info(f"Starting batch registration: count={args.count}, threads={args.threads}")
    await perform_batch_registration(pool, args.count, args.threads)
    
    # 最终保存确保同步
    await pool.save()
    log.info("Batch registration completed successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    except Exception as e:
        log.error(f"Execution failed: {e}")
