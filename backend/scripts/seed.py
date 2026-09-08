"""Seed five in-flight pipelines covering the scenarios we exercise locally.
Run inside docker compose (so dramatiq + redis are up).

Usage:
    docker compose exec api python scripts/seed.py
"""
from __future__ import annotations

import os
import time

import httpx

API_BASE = os.environ.get('CANTATA_API_BASE', 'http://localhost:8000')


SCENARIOS = [
    {
        'label': 'scenario_1',
        'env': {},
        'editor_email': 'editor1@example.test',
    },
    {
        'label': 'scenario_2',
        'env': {'FAKE_STT_FAILURE_MODE': 'transient_5xx'},
        'editor_email': 'editor2@example.test',
    },
    {
        'label': 'scenario_3',
        'env': {'FAKE_STT_FAILURE_MODE': 'crash_after_vendor_accepted'},
        'editor_email': 'editor3@example.test',
    },
    {
        'label': 'scenario_4',
        'env': {'FAKE_SMTP_FAILURE_MODE': 'transient_5xx'},
        'editor_email': 'editor4@example.test',
    },
    {
        'label': 'scenario_5',
        'env': {'FAKE_DELIVERY_FAILURE_MODE': 'webhook_5xx'},
        'editor_email': 'editor5@example.test',
    },
]


def main() -> None:
    print(f'seeding against {API_BASE}')
    for scenario in SCENARIOS:
        # Note: the worker process must be restarted with the env var set for the
        # scenario to actually trigger it. Run one scenario at a time. This script
        # primarily creates the pipeline rows.
        print(f'creating pipeline for scenario={scenario["label"]}')
        for key, value in scenario['env'].items():
            print(f'  expected env on worker: {key}={value}')
        resp = httpx.post(
            f'{API_BASE}/pipelines',
            json={
                'audioUrl': 'https://example.test/audio.wav',
                'customerWebhookUrl': 'https://example.test/customer/webhook',
                'editorEmail': scenario['editor_email'],
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        print(f'  created pipeline_id={resp.json()["id"]}')
        time.sleep(0.2)


if __name__ == '__main__':
    main()
