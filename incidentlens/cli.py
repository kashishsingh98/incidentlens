import argparse
import asyncio
import json

from incidentlens.investigator import investigate
from incidentlens.store import baseline, change_index


def main():
    parser = argparse.ArgumentParser(description="IncidentLens local incident lab")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local dashboard")
    serve.add_argument("--port", type=int, default=8000)
    demo = sub.add_parser("demo", help="Reproduce and investigate an index-removal incident")
    demo.add_argument("--mode", choices=["rules", "llm"], default="rules")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("incidentlens.api:app", host="127.0.0.1", port=args.port, workers=1)
    else:
        experiment = baseline()["experiment_id"]
        change_index(experiment, restore=False)
        print(json.dumps(asyncio.run(investigate(experiment, args.mode)), indent=2))


if __name__ == "__main__":
    main()
