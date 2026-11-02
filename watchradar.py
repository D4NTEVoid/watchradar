
#!/usr/bin/env python3

import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import requests


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_URL = "https://bbradar.io"
FRONTEND_TOKEN_URL = f"{BASE_URL}/api/frontend-token"
CSRF_TOKEN_URL = f"{BASE_URL}/api/csrf-token"
PROGRAMS_URL = f"{BASE_URL}/api/programs"

DB_PATH = Path(
    os.getenv("WATCHRADAR_DB_PATH", "/databases/watchtower.db")
)

REQUEST_TIMEOUT = (10, 30)
NOTIFICATION_DELAY = float(os.getenv("NOTIFICATION_DELAY", "2"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "")
TELEGRAM_GROUP_THREAD_ID = os.getenv("TELEGRAM_GROUP_THREAD_ID", "")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("watchradar")


# --------------------------------------------------
# Database
# --------------------------------------------------

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS radar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_name TEXT UNIQUE NOT NULL,
                platform_name_href TEXT,
                date_updated TEXT,
                telegram_sent INTEGER NOT NULL DEFAULT 0,
                discord_sent INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Migrate existing databases without re-notifying
        # programs already stored by the original script.

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(radar)")
        }

        if "telegram_sent" not in columns:
            conn.execute("""
                ALTER TABLE radar
                ADD COLUMN telegram_sent INTEGER NOT NULL DEFAULT 1
            """)

        if "discord_sent" not in columns:
            conn.execute("""
                ALTER TABLE radar
                ADD COLUMN discord_sent INTEGER NOT NULL DEFAULT 1
            """)


def insert_program(conn, name, link, date):
    cursor = conn.execute("""
        INSERT OR IGNORE INTO radar (
            program_name,
            platform_name_href,
            date_updated,
            telegram_sent,
            discord_sent
        )
        VALUES (?, ?, ?, 0, 0)
    """, (name, link, date))

    return cursor.rowcount == 1


def get_pending_notifications(conn):
    return conn.execute("""
        SELECT *
        FROM radar
        WHERE telegram_sent = 0 OR discord_sent = 0
        ORDER BY id ASC
    """).fetchall()


def mark_notification_sent(conn, program_id, platform):
    if platform not in {"telegram", "discord"}:
        raise ValueError("Invalid notification platform")

    # The column name comes only from the fixed allowlist above.
    conn.execute(
        f"UPDATE radar SET {platform}_sent = 1 WHERE id = ?",
        (program_id,),
    )


# --------------------------------------------------
# BBRadar API
# --------------------------------------------------

def fetch_programs():
    session = requests.Session()

    session.headers.update({
        "User-Agent": "WatchRadar/1.0",
        "Accept": "application/json",
    })

    try:
        # Obtain frontend token
        response = session.get(
            FRONTEND_TOKEN_URL,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        frontend_token = response.json()

        if not isinstance(frontend_token, dict):
            raise ValueError("Unexpected frontend token response")

        # Obtain CSRF token
        response = session.post(
            CSRF_TOKEN_URL,
            json=frontend_token,
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        csrf_data = response.json()
        csrf_token = csrf_data.get("csrf_token")

        if not csrf_token:
            raise ValueError("CSRF token missing from API response")

        # Fetch programs
        response = session.get(
            PROGRAMS_URL,
            headers={"X-Csrf-Token": csrf_token},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()

        # Accept either a direct list or a common wrapped response.
        if isinstance(data, dict):
            data = data.get("programs")

        if not isinstance(data, list):
            raise ValueError("Unexpected programs API response")

        return data

    finally:
        session.close()


# --------------------------------------------------
# Program formatting
# --------------------------------------------------

def is_vdp(bounty_max):
    if bounty_max is None:
        return False

    try:
        return Decimal(str(bounty_max)) == 0
    except (InvalidOperation, ValueError):
        return False


def format_program(program):
    name = program.get("name")
    date = program.get("date_launched")
    raw_link = program.get("link")

    if not isinstance(name, str) or not name.strip():
        return None

    if not isinstance(raw_link, str) or not raw_link.strip():
        return None

    name = name.strip()
    link = urljoin(BASE_URL + "/", raw_link.strip())

    bounty_min = program.get("bounty_min")
    bounty_max = program.get("bounty_max")

    if is_vdp(bounty_max):
        bounty_text = "VDP"
    else:
        minimum = "Unknown" if bounty_min is None else str(bounty_min)
        maximum = "Unknown" if bounty_max is None else str(bounty_max)
        bounty_text = f"${minimum} - ${maximum}"

    message = (
        f"New bug bounty program detected!\n\n"
        f"Program: {name}\n"
        f"Launched: {date or 'Unknown'}\n"
        f"Link: {link}\n"
        f"Bounty: {bounty_text}"
    )

    return {
        "name": name,
        "date": date,
        "link": link,
        "message": message,
    }


# --------------------------------------------------
# Telegram
# --------------------------------------------------

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram is not configured.")
        return False

    destinations = []

    if TELEGRAM_CHAT_ID:
        destinations.append({
            "chat_id": TELEGRAM_CHAT_ID,
        })

    if TELEGRAM_GROUP_CHAT_ID:
        group = {
            "chat_id": TELEGRAM_GROUP_CHAT_ID,
        }

        if TELEGRAM_GROUP_THREAD_ID:
            group["message_thread_id"] = TELEGRAM_GROUP_THREAD_ID

        destinations.append(group)

    if not destinations:
        logger.warning("No Telegram destinations configured.")
        return False

    endpoint = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    all_sent = True

    for destination in destinations:
        payload = {
            **destination,
            "text": message,
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            result = response.json()

            if not result.get("ok"):
                raise RuntimeError("Telegram API rejected the message")

            logger.info("Telegram notification delivered.")

        except (requests.RequestException, ValueError, RuntimeError) as exc:
            logger.error("Telegram notification failed: %s", exc)
            all_sent = False

    return all_sent


# --------------------------------------------------
# Discord
# --------------------------------------------------

def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord is not configured.")
        return False

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        logger.info("Discord notification delivered.")
        return True

    except requests.RequestException as exc:
        logger.error("Discord notification failed: %s", exc)
        return False


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    initialize_database()

    logger.info("Fetching programs from BBRadar...")

    try:
        programs = fetch_programs()
    except (
        requests.RequestException,
        ValueError,
        RuntimeError,
    ) as exc:
        logger.error("Failed to retrieve programs: %s", exc)
        return 1

    new_programs = 0

    with get_connection() as conn:
        for raw_program in programs:
            if not isinstance(raw_program, dict):
                continue

            program = format_program(raw_program)

            if not program:
                logger.warning("Skipping an invalid program entry.")
                continue

            inserted = insert_program(
                conn,
                program["name"],
                program["link"],
                program["date"],
            )

            if inserted:
                new_programs += 1
                logger.info("New program discovered: %s", program["name"])

        pending = get_pending_notifications(conn)

        logger.info("New programs: %d", new_programs)
        logger.info("Pending notification records: %d", len(pending))

        for record in pending:
            message = (
                f"New bug bounty program detected!\n\n"
                f"Program: {record['program_name']}\n"
                f"Launched: {record['date_updated'] or 'Unknown'}\n"
                f"Link: {record['platform_name_href'] or 'Unknown'}"
            )

            if not record["telegram_sent"]:
                if send_telegram(message):
                    mark_notification_sent(
                        conn, record["id"], "telegram"
                    )

            if not record["discord_sent"]:
                if send_discord(message):
                    mark_notification_sent(
                        conn, record["id"], "discord"
                    )

            conn.commit()
            time.sleep(NOTIFICATION_DELAY)

    logger.info("WatchRadar execution completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
