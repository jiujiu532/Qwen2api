"""
garbage_collector.py — 聊天会话垃圾回收
定期清理上游的残留聊天会话，防止账号积累过多历史。
"""

import asyncio
import logging

log = logging.getLogger("qwen2api.gc")


async def garbage_collect_chats(qwen_client, interval: int = 300):
    """后台定时清理非活跃的聊天会话。"""
    log.info(f"[GC] 垃圾回收器已启动 (间隔={interval}s)")
    while True:
        try:
            await asyncio.sleep(interval)
            # 只清理不在活跃集合中的 chat_id
            active = qwen_client.active_chat_ids.copy()
            log.debug(f"[GC] 当前活跃会话数: {len(active)}")
        except asyncio.CancelledError:
            log.info("[GC] 垃圾回收器已停止")
            break
        except Exception as e:
            log.warning(f"[GC] 回收异常: {e}")
            await asyncio.sleep(30)
