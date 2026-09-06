from .common import ExternalAdapter
class CodexWorkerAdapter(ExternalAdapter):
    def __init__(self, transport, endpoint): super().__init__(transport, endpoint, "codex_worker")
    def start_run(self, context, plan):
        if context.mode != "fde" or not context.file_scope: raise ValueError("Codex Worker 需要 FDE 模式和受限文件范围")
        return super().start_run(context, plan)
