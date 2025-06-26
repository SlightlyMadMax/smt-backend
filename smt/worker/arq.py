from typing import Optional

from arq import create_pool

from smt.worker.settings import WorkerSettings


_arq_service_instance = None


class ARQService:
    def __init__(self):
        self.redis_settings = WorkerSettings.redis_settings
        self.pool = None

    async def get_pool(self):
        """Get or create Redis pool for ARQ"""
        if self.pool is None:
            self.pool = await create_pool(self.redis_settings)
        return self.pool

    async def enqueue(
        self, task_name: str, *args, delay: Optional[int] = None, defer_until: Optional[int] = None, **kwargs
    ) -> str:
        pool = await self.get_pool()

        job = await pool.enqueue_job(task_name, *args, _defer_by=delay, _defer_until=defer_until, **kwargs)

        return job.job_id

    async def close(self):
        """Close the Redis pool"""
        if self.pool:
            await self.pool.close()


def get_arq_service() -> ARQService:
    global _arq_service_instance
    if _arq_service_instance is None:
        _arq_service_instance = ARQService()
    return _arq_service_instance
