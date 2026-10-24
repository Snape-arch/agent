"""Small asynchronous index batches backed by the existing durable SQLite outbox."""
import asyncio


class DocumentIndexWorker:
    def __init__(self,store,vector,batch_limit=32):
        self.store=store;self.vector=vector;self.batch_limit=batch_limit
        self.task=None;self.last_error='';self.last_result=None

    def status(self):
        with self.store._conn() as c:
            pending,failed=c.execute("SELECT COUNT(*),COALESCE(SUM(error<>''),0) FROM knowledge_vector_outbox_v2 WHERE processed_at='' ").fetchone()
        running=self.task is not None and not self.task.done()
        return dict(state='indexing' if running and pending else 'failed' if failed or self.last_error else 'pending' if pending else 'ready',
                    pending=int(pending),failed=int(failed),running=running,error=self.last_error,
                    durable=True,status_url='/api/documents/indexing')

    def start(self):
        if self.task is None or self.task.done():
            self.last_error='';self.task=asyncio.create_task(self.run())

    async def run(self):
        try:
            while (await asyncio.to_thread(self.status))['pending']:
                result=await asyncio.to_thread(self.vector.refresh,limit=self.batch_limit)
                self.last_result=result
                if result.get('failed') or result.get('error'):
                    self.last_error=result.get('error') or 'vector_batch_failed';break
                if not result.get('processed') and (await asyncio.to_thread(self.status))['pending']:
                    self.last_error='vector_batch_no_progress';break
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            # Native encoding already running may finish its current bounded
            # batch; all unacknowledged events stay durable for the next process.
            raise
        except Exception as exc:self.last_error=type(exc).__name__

    async def close(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
