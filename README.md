# WatchRadar

**Monitor newly listed bug bounty programs and receive real-time notifications.**

WatchRadar is a lightweight Python tool that monitors the public program listing API of [BBRadar](https://bbradar.io/), detects newly listed bug bounty programs, tracks them in a local SQLite database, and sends notifications through Telegram and Discord.

## Features

- **Automated program discovery:** Retrieves program listings from BBRadar.
- **New program detection:** Identifies programs that have not previously been recorded.
- **SQLite storage:** Maintains a persistent local database of discovered programs.
- **Telegram notifications:** Sends alerts to a personal chat and/or a Telegram group topic.
- **Discord notifications:** Delivers alerts through a Discord webhook.
- **Notification retry:** Keeps track of delivery status and retries unsuccessful notifications on subsequent executions.
- **Configurable deployment:** Supports environment-based configuration for database paths and notification credentials.

## How It Works

1. Establishes a session with BBRadar.
2. Retrieves the frontend token and obtains a CSRF token.
3. Requests the available program listings.
4. Extracts program information, including name, launch date, URL, and bounty range.
5. Checks the SQLite database for previously discovered programs.
6. Stores newly discovered entries.
7. Sends notifications through configured integrations.
8. Records notification delivery status to support retries.

## Requirements

- Python 3.9+
- Requests
- An internet connection
- Optional: Telegram bot and Discord webhook for notifications

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/watchradar.git
cd watchradar
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Configure the required values:

```dotenv
WATCHRADAR_DB_PATH=/databases/watchtower.db

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

TELEGRAM_GROUP_CHAT_ID=
TELEGRAM_GROUP_THREAD_ID=

DISCORD_WEBHOOK_URL=

NOTIFICATION_DELAY=2
```

The script reads environment variables directly and does not automatically load `.env`.

Load the configuration before execution:

```bash
set -a
source .env
set +a
```

Telegram and Discord are optional. Configure whichever notification integrations you want to use.

## Usage

Run WatchRadar:

```bash
python3 watchradar.py
```

For scheduled monitoring, you can use cron. For example, to execute it every 30 minutes:

```cron
*/30 * * * * set -a; source /path/to/watchradar/.env; set +a; /usr/bin/python3 /path/to/watchradar/watchradar.py
```

Adjust the paths to match your environment.

## Database

WatchRadar uses SQLite to maintain discovered program records.

Default database:

```text
/databases/watchtower.db
```

The `radar` table stores:

| Column | Description |
|---|---|
| `id` | Unique record identifier |
| `program_name` | Unique program name |
| `platform_name_href` | Program URL |
| `date_updated` | Program launch date |
| `bounty` | Bounty range or VDP classification |
| `telegram_sent` | Telegram delivery status |
| `discord_sent` | Discord delivery status |

Notification status is tracked independently for each platform.

Existing databases are migrated automatically when the new notification and bounty columns are missing.

## Security Considerations

- Keep Telegram bot tokens and Discord webhook URLs outside the source code.
- Never commit `.env` or database files.
- Use this tool in accordance with BBRadar's terms and applicable rate limits.
- Notification delivery uses retries; duplicate alerts are possible if a process stops after sending a message but before recording its delivery status.

## Responsible Use

WatchRadar is intended for bug bounty researchers and security professionals who want to monitor publicly listed vulnerability disclosure and bug bounty programs.

It discovers program listings; it does not perform vulnerability scanning, exploitation, or testing of program assets.

Always follow the rules and scope requirements of individual bug bounty programs.

## License

Choose an appropriate license after confirming that your use of the BBRadar API and any included third-party components complies with their respective terms.
