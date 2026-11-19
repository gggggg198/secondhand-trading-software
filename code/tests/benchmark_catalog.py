"""Reproducible REQ-031 HTTP check on an isolated PostgreSQL schema."""

import argparse
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from statistics import quantiles
from threading import Barrier
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from psycopg import sql
from psycopg.conninfo import make_conninfo

from whale_market.db import apply_migrations, open_database

CLIENTS = 20
WARMUP = 200
SAMPLES = 1000


@contextmanager
def isolated_database(database_url):
    schema = f"bench_whale_{uuid4().hex}"
    identifier = sql.Identifier(schema)
    with open_database(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
    try:
        target = make_conninfo(database_url, options=f"-c search_path={schema}")
        apply_migrations(target)
        yield target
    finally:
        with open_database(database_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(identifier))


def seed(database_url):
    with open_database(database_url) as connection:
        connection.execute(
            """
            INSERT INTO account (username, password_hash)
            SELECT 'BenchUser' || i, 'synthetic-benchmark' FROM generate_series(1, 2000) i;

            INSERT INTO product (seller_id, title, description, category, condition, price, status,
                created_at, published_at, approved_digest)
            SELECT 1 + i % 2000, 'Item-' || lpad(i::text, 5, '0'),
                CASE WHEN i % 3 = 0 THEN 'lamp campus' ELSE 'keyboard campus' END,
                (ARRAY['书籍', '电子产品', '生活用品', '运动用品', '其他'])[1 + i % 5],
                '九成新', 1.00 + i % 500,
                CASE WHEN i % 4 = 0 THEN 'OFFLINE' ELSE 'PUBLISHED' END,
                '2026-01-01T00:00:00Z'::timestamptz,
                '2026-01-01T00:00:00Z'::timestamptz + (i % 31) * INTERVAL '1 hour',
                'synthetic-benchmark'
            FROM generate_series(1, 10000) i;

            INSERT INTO reservation (product_id, buyer_id, product_title, price, location, meeting_at,
                created_at, updated_at, status, reason)
            SELECT p.id, 1 + (p.seller_id + n) % 2000, p.title, p.price, '校园验收地点',
                '2026-02-02T00:00:00Z', '2026-02-01T00:00:00Z',
                '2026-02-01T01:00:00Z', 'CANCELLED', '生成的历史记录'
            FROM product p CROSS JOIN generate_series(1, 2) n;

            ANALYZE account;
            ANALYZE product;
            ANALYZE reservation;
            """
        )
        sizes = connection.execute(
            """
            SELECT (SELECT count(*) FROM account) AS accounts,
                (SELECT count(*) FROM product) AS products,
                (SELECT count(*) FROM reservation) AS reservations
            """
        ).fetchone()
        rows = connection.execute(
            """
            SELECT id, title, description, category, price FROM product
            WHERE status = 'PUBLISHED' ORDER BY published_at DESC, id
            """
        ).fetchall()
    assert sizes == {"accounts": 2000, "products": 10000, "reservations": 20000}
    return sizes, rows


def build_cases(rows):
    queries = [
        {},
        {"page": 3},
        {"page": 201},
        {"q": "ITEM-00001"},
        {"q": "missing"},
        {"q": "lamp"},
        {"q": "keyboard", "page": 4},
        {"category": "电子产品"},
        {"category": "书籍", "page": 2},
        {"minimum": "0.01", "maximum": "25"},
        {"minimum": "225", "maximum": "225"},
        {"minimum": "490"},
        {"category": "其他", "maximum": "20"},
        {"q": "lamp", "category": "生活用品", "minimum": "75", "maximum": "250"},
        {"q": "CAMPUS", "category": "运动用品", "minimum": "490", "page": 2},
        {"q": "ITEM-00999", "category": "电子产品"},
        {"q": "item-", "category": "书籍", "maximum": "100", "page": 9},
        {"q": "lamp", "category": "书籍", "minimum": "1", "maximum": "500", "page": 2},
        {"q": "keyboard", "category": "其他", "minimum": "200", "page": 3},
        {"q": "item-0", "minimum": "0", "maximum": "500", "page": 6},
    ]
    cases = []
    for query in queries:
        keyword = query.get("q", "").casefold()
        lower = Decimal(query.get("minimum", "0"))
        upper = Decimal(query.get("maximum", "100000"))
        matches = [
            row["id"]
            for row in rows
            if (
                keyword in row["title"].casefold()
                or keyword in row["description"].casefold()
            )
            and row["category"] == query.get("category", row["category"])
            and lower <= row["price"] <= upper
        ]
        page = query.get("page", 1)
        start = (page - 1) * 20
        cases.append((query, len(matches), matches[start : start + 20]))
    return cases


@contextmanager
def live_application(database_url):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}/api"
    process = subprocess.Popen(
        [sys.executable, "-m", "whale_market.cli", "serve", "--port", str(port)],
        env={**os.environ, "WHALE_DATABASE_URL": database_url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("Application did not start.")
            try:
                with build_opener(ProxyHandler({})).open(
                    base + "/health", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except URLError:
                sleep(0.1)
        else:
            raise RuntimeError("Application did not become ready.")
        yield base
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def sample(base, cases, count):
    barrier = Barrier(CLIENTS, timeout=20)

    def request(index):
        query, expected_total, expected_ids = cases[index % len(cases)]
        if index < CLIENTS:
            barrier.wait()
        started = perf_counter()
        try:
            path = base + "/products?" + urlencode(query)
            with build_opener(ProxyHandler({})).open(path, timeout=8) as response:
                body = json.load(response)
                status = response.status
            ids = [item["id"] for item in body["items"]]
            correct = (
                body["total"] == expected_total
                and body["page"] == query.get("page", 1)
                and ids == expected_ids
                and all(row["status"] == "PUBLISHED" for row in body["items"])
            )
        except (URLError, ValueError, KeyError, TypeError, OSError) as error:
            status = error.code if isinstance(error, HTTPError) else 0
            correct = False
        return {
            "index": index + 1,
            "query": query,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "status": status,
            "correct": correct,
        }

    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        return list(pool.map(request, range(count)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="write all 1000 measurements as JSONL",
    )
    args = parser.parse_args()
    database_url = os.environ["WHALE_TEST_DATABASE_URL"]
    with isolated_database(database_url) as temporary:
        sizes, rows = seed(temporary)
        cases = build_cases(rows)
        with live_application(temporary) as base:
            sample(base, cases, WARMUP)
            measurements = sample(base, cases, SAMPLES)

    with args.output.open("w", encoding="utf-8") as output:
        for item in measurements:
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
    elapsed = [item["elapsed_ms"] for item in measurements]
    fast = sum(item["correct"] and item["elapsed_ms"] <= 2000 for item in measurements)
    errors = sum(item["status"] != 200 for item in measurements)
    incorrect = sum(
        item["status"] == 200 and not item["correct"] for item in measurements
    )
    print(
        json.dumps(
            {
                **sizes,
                "concurrency": CLIENTS,
                "warmup": WARMUP,
                "sample_size": SAMPLES,
                "CPU_affinity": sorted(os.sched_getaffinity(0))
                if hasattr(os, "sched_getaffinity")
                else None,
                "fast_correct": fast,
                "system_errors": errors,
                "incorrect_successes": incorrect,
                "p95_ms": round(quantiles(elapsed, n=100, method="inclusive")[94], 3),
                "max_ms": max(elapsed),
                "passed": fast >= 950 and errors <= 10 and incorrect == 0,
            }
        )
    )
    return 0 if fast >= 950 and errors <= 10 and incorrect == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
