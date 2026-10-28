"""Get a verified bank session token for a demo customer, for manual MCP testing.

    uv run python scripts/demo_session.py C-1001 2468

Prints the token. Use it as "Authorization: Bearer <token>" in MCP Inspector,
or as BANK_SESSION_TOKEN for a stdio client. The session times out after 10
idle minutes, like a real call.
"""

import sys

import httpx

from app.config import settings


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: demo_session.py CUSTOMER_CODE PIN   e.g. C-1001 2468")
    customer_code, pin = sys.argv[1], sys.argv[2]
    with httpx.Client(base_url=settings.bank_api_url, timeout=5) as http:
        token = http.post("/sessions").json()["session_token"]
        verified = http.post(
            "/sessions/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={"customer_code": customer_code, "pin": pin},
        )
    if verified.status_code != 200:
        sys.exit(f"Verification failed: {verified.json().get('error', verified.text)}")
    print(token)


if __name__ == "__main__":
    main()
