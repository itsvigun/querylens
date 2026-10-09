"""Docker/PaaS entrypoint; no migrations, seed, ingestion or provider calls."""

import os

import uvicorn


def main():
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid HTTP port")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        access_log=False,
        proxy_headers=False,
        timeout_graceful_shutdown=130,
    )


if __name__ == "__main__":
    main()
