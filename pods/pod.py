class Pod:
    def __init__(self, context: str, namespace: str, service: str, port: int):
        self.context = context
        self.namespace = namespace
        self.service = service
        self.port = port

    def get_service(self) -> str:
        return self.service

    def get_namespace(self) -> str:
        return self.namespace

    def get_context(self) -> str:
        return self.context

    def get_port(self) -> int:
        return self.port
