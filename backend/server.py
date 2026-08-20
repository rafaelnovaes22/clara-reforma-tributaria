from __future__ import annotations

from clara.application import ClaraApplication
from clara.http_api import create_http_server
from clara.settings import RuntimeSettings

SETTINGS = RuntimeSettings.from_environment()
APPLICATION = ClaraApplication.build(SETTINGS)


def main() -> None:
    server = create_http_server(APPLICATION)
    APPLICATION.logger.emit(
        "info",
        "server_started",
        host=SETTINGS.host,
        port=SETTINGS.port,
        environment=SETTINGS.environment,
        graph_ready=APPLICATION.conversation.graph_ready,
        openai_configured=bool(SETTINGS.openai_api_key),
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        APPLICATION.logger.emit("info", "server_interrupted")
    finally:
        server.server_close()
        APPLICATION.logger.emit("info", "server_stopped")


if __name__ == "__main__":
    main()
