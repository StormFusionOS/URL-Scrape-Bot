"""
Competitor Intelligence Module - Entry Point

Run with: python -m competitor_intel [command]

Commands:
    orchestrator    Start the competitor job orchestrator
    cli             Interactive CLI for competitor intel
    test            Run a single competitor test
"""

import sys
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Competitor Intelligence Module",
        prog="competitor_intel"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Orchestrator command
    orch_parser = subparsers.add_parser(
        "orchestrator",
        help="Start the competitor job orchestrator"
    )
    orch_parser.add_argument(
        "--worker-name",
        default="competitor_worker_1",
        help="Worker name for heartbeat tracking"
    )
    orch_parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run single batch then exit"
    )
    orch_parser.add_argument(
        "--single-competitor",
        type=int,
        help="Process single competitor ID then exit"
    )

    # Test command
    test_parser = subparsers.add_parser(
        "test",
        help="Run a test on a single competitor"
    )
    test_parser.add_argument(
        "competitor_id",
        type=int,
        help="Competitor ID to test"
    )
    test_parser.add_argument(
        "--module",
        choices=["site_crawl", "serp_track", "citations", "reviews", "technical", "services", "synthesis"],
        help="Specific module to test"
    )

    args = parser.parse_args()

    if args.command == "orchestrator":
        from competitor_intel.jobs.competitor_job_orchestrator import CompetitorJobOrchestrator
        orchestrator = CompetitorJobOrchestrator(worker_name=args.worker_name)
        if args.single_competitor:
            orchestrator.run_single_competitor(args.single_competitor)
        else:
            orchestrator.run(test_mode=args.test_mode)

    elif args.command == "test":
        from competitor_intel.cli import test_competitor
        test_competitor(args.competitor_id, args.module)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
