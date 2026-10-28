"""Load demo customers from profiles.yaml into the local database."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")
PROFILES = ROOT / "data" / "seed" / "profiles.yaml"


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def main() -> None:
    data = yaml.safe_load(PROFILES.read_text())
    now = datetime.now(timezone.utc)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        # Start fresh every time so seeding is repeatable.
        cur.execute(
            "truncate audit_log, disputes, transfers, transactions, "
            "cards, accounts, sessions, customers restart identity cascade"
        )

        for c in data["customers"]:
            cur.execute(
                "insert into customers (customer_code, full_name, pin_hash) "
                "values (%s, %s, %s) returning id",
                (c["code"], c["name"], hash_pin(c["pin"])),
            )
            customer_id = cur.fetchone()[0]

            for a in c["accounts"]:
                cur.execute(
                    "insert into accounts (customer_id, account_type, last4, balance_cents) "
                    "values (%s, %s, %s, %s) returning id",
                    (customer_id, a["type"], a["last4"], a["balance_cents"]),
                )
                account_id = cur.fetchone()[0]

                if "card_last4" in a:
                    cur.execute(
                        "insert into cards (account_id, last4) values (%s, %s)",
                        (account_id, a["card_last4"]),
                    )

                for t in a.get("transactions", []):
                    cur.execute(
                        "insert into transactions "
                        "(account_id, merchant, amount_cents, status, posted_at) "
                        "values (%s, %s, %s, %s, %s)",
                        (
                            account_id,
                            t["merchant"],
                            t["amount_cents"],
                            t.get("status", "posted"),
                            now - timedelta(days=t["days_ago"]),
                        ),
                    )

        conn.commit()
    print(f"Seeded {len(data['customers'])} customers.")


if __name__ == "__main__":
    main()