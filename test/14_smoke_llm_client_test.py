#!/usr/bin/env python3
"""
Smoke test for ILAAS LLM client.

Usage:
    PYTHONPATH=. python test/14_smoke_llm_client_test.py

Optional:
    PYTHONPATH=. python test/14_smoke_llm_client_test.py --model qwen-3.6-35b-instruct
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import settings
from src.config.paths import paths
from src.io.json_io import write_json
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test for ILAAS LLM client."
    )

    parser.add_argument(
        "--model",
        default=settings.ilaas_model,
        help="Model to test.",
    )

    parser.add_argument(
        "--skip-model-list",
        action="store_true",
        help="Skip GET /models.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="smoke_llm_client",
        log_file=paths.logs_dir / "smoke_llm_client.log",
    )

    client = ILAASClient(
        model=args.model,
        max_tokens=200,
        temperature=0.0,
        timeout_seconds=120,
    )

    logger.info("=" * 80)
    logger.info("LLM CLIENT SMOKE TEST")
    logger.info("=" * 80)
    logger.info(f"Base URL: {settings.ilaas_base_url}")
    logger.info(f"Model: {args.model}")
    logger.info(f"API key configured: {bool(settings.ilaas_api_key)}")

    models = []

    if not args.skip_model_list:
        models = client.list_models()
        logger.info(f"Available models: {models}")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict JSON API. "
                "Return only one valid JSON object. "
                "No markdown. No code fences. No explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                'Return exactly this JSON object and nothing else: '
                '{"status":"ok","task":"smoke_test","answer":"pong"}'
            ),
        },
    ]

    payload, first_response, repair_response = client.chat_json(
        messages=messages,
        model=args.model,
        max_tokens=200,
        temperature=0.0,
        repair_on_fail=True,
    )

    output_path = paths.prototype_dir / "_smoke_llm_client_response.json"

    write_json(
        output_path,
        {
            "model": args.model,
            "models_available": models,
            "payload": payload,
            "raw_content": first_response.content,
            "repair_used": repair_response is not None,
            "repair_content": repair_response.content if repair_response else "",
        },
    )

    logger.info(f"Parsed payload: {payload}")
    logger.info(f"Repair used: {repair_response is not None}")
    logger.info(f"Output: {output_path}")
    logger.info("LLM smoke test OK")

    print("=" * 80)
    print("LLM CLIENT SMOKE TEST COMPLETE")
    print("=" * 80)
    print(f"Model: {args.model}")
    print(f"Available models count: {len(models)}")
    print(f"Parsed payload: {payload}")
    print(f"Repair used: {repair_response is not None}")
    print(f"Output: {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()