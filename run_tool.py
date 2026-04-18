from __future__ import annotations

import argparse
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Zero Hour Replay Analyzer web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open browser automatically.")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if args.open:
        webbrowser.open(url)

    uvicorn.run("replay_tool.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

