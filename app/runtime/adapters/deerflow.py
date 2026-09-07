from .common import ExternalAdapter
class DeerFlowAdapter(ExternalAdapter):
    def __init__(self, transport, endpoint): super().__init__(transport, endpoint, "deerflow")
