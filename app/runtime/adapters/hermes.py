from .common import ExternalAdapter
class HermesAdapter(ExternalAdapter):
    def __init__(self, transport, endpoint): super().__init__(transport, endpoint, "hermes")
    def start_run(self, context, plan):
        return super().start_run(context, plan)
    def stream_events(self, run_id, cursor=None):
        events=super().stream_events(run_id, cursor)
        for event in events:
            if event.event_type.value == "plan.created": event.payload.update({"status":"pending_review","kind":"growth_proposal"})
        return events
