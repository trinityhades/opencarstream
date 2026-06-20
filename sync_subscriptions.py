#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["browser-cookie3", "requests"]
# ///
"""
Fetch your YouTube subscriptions and write subscriptions.json.

Uses YouTube's internal API — single session, no video iteration, completes in seconds.

Usage (read cookies directly from your browser — no manual export needed):
  uv run sync_subscriptions.py --browser chrome
  uv run sync_subscriptions.py --browser firefox

Usage (with a manually exported Netscape cookies.txt file):
  uv run sync_subscriptions.py --cookies /path/to/cookies.txt

Supported browser values: chrome, chromium, firefox, brave, edge, opera, safari
"""

import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import browser_cookie3
import requests

BROWSERS = ["chrome", "chromium", "firefox", "brave", "edge", "opera", "safari"]
INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/browse"
CLIENT_VERSION = "2.20240101.00.00"
SUBS_BROWSE_IDS = ("FEsubscriptions", "FEchannels")
AUTH_COOKIE_NAMES = (
    "SAPISID",
    "__Secure-3PAPISID",
    "APISID",
    "__Secure-1PAPISID",
)


def cookies_from_browser(browser: str) -> dict[str, str]:
    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        print(f"‼ Browser '{browser}' not supported", file=sys.stderr)
        sys.exit(1)
    jar = fn(domain_name="youtube.com")
    return {c.name: c.value for c in jar}


def cookies_from_file(path: Path) -> dict[str, str]:
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar if "youtube.com" in c.domain}


def auth_cookie_value(cookies: dict[str, str]) -> str:
    for name in AUTH_COOKIE_NAMES:
        value = cookies.get(name, "")
        if value:
            return value
    return ""


def auth_cookie_names_present(cookies: dict[str, str]) -> list[str]:
    return [name for name in AUTH_COOKIE_NAMES if cookies.get(name, "")]


def make_headers(cookies: dict[str, str]) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-Origin": "https://www.youtube.com",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": CLIENT_VERSION,
        "Content-Type": "application/json",
    }
    sid = auth_cookie_value(cookies)
    if sid:
        ts = str(int(time.time()))
        h = hashlib.sha1(f"{ts} {sid} https://www.youtube.com".encode()).hexdigest()
        headers["Authorization"] = f"SAPISIDHASH {ts}_{h}"
    headers["X-Goog-AuthUser"] = "0"
    return headers


def innertube_browse(
    session: requests.Session,
    cookies: dict,
    headers: dict,
    browse_id: str,
    token: str | None = None,
) -> dict:
    body: dict = {"context": {"client": {"clientName": "WEB", "clientVersion": CLIENT_VERSION}}}
    if token:
        body["continuation"] = token
    else:
        body["browseId"] = browse_id

    def _post(req_headers: dict[str, str]) -> requests.Response:
        return session.post(INNERTUBE_URL, cookies=cookies, headers=req_headers, json=body, timeout=30)

    resp = _post(headers)

    # Safari and some Google account cookie combinations may not expose the
    # expected SAPISID cookie. If the authenticated request fails hard, retry
    # once without Authorization so we can still succeed with a less strict
    # session shape.
    if resp.status_code >= 500 and headers.get("Authorization"):
        retry_headers = dict(headers)
        retry_headers.pop("Authorization", None)
        resp = _post(retry_headers)

    if resp.status_code != 200:
        detail = resp.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "…"
        raise RuntimeError(
            f"YouTube browse failed with HTTP {resp.status_code}: {detail or '(empty response)'}"
        )

    try:
        return resp.json()
    except ValueError as exc:
        detail = resp.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "…"
        raise RuntimeError(
            f"YouTube browse returned invalid JSON: {detail or '(empty response)'}"
        ) from exc


def extract_channels_and_token(data: dict) -> tuple[list[dict], str | None]:
    channels = []

    def walk(obj):
        if isinstance(obj, dict):
            renderer = None
            for key in ("channelRenderer", "gridChannelRenderer", "subscriptionChannelRenderer"):
                if key in obj:
                    renderer = obj[key]
                    break
            if renderer is not None:
                r = renderer
                chan_id = r.get("channelId", "")
                name = r.get("title", {}).get("simpleText", "")
                if not name:
                    runs = r.get("title", {}).get("runs", [])
                    if runs:
                        name = "".join(run.get("text", "") for run in runs)
                if chan_id and name:
                    channels.append({"name": name, "url": f"https://www.youtube.com/channel/{chan_id}"})
            else:
                for v in obj.values():
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    # Find continuation token
    token = None

    def find_token(obj):
        nonlocal token
        if isinstance(obj, dict):
            if "continuationCommand" in obj:
                token = obj["continuationCommand"].get("token")
                return
            for v in obj.values():
                find_token(v)
                if token:
                    return
        elif isinstance(obj, list):
            for item in obj:
                find_token(item)
                if token:
                    return

    find_token(data)
    return channels, token


def fetch_subscriptions(cookies: dict[str, str]) -> list[dict]:
    session = requests.Session()
    headers = make_headers(cookies)

    for browse_id in SUBS_BROWSE_IDS:
        all_channels: list[dict] = []
        seen: set[str] = set()
        token = None
        page = 0

        while True:
            data = innertube_browse(session, cookies, headers, browse_id, token)
            channels, token = extract_channels_and_token(data)

            for ch in channels:
                if ch["url"] not in seen:
                    seen.add(ch["url"])
                    all_channels.append(ch)

            page += 1
            print(
                f"  {browse_id} page {page}: {len(all_channels)} channels so far…",
                end="\r",
            )

            if all_channels or not token:
                break

        print()
        if all_channels:
            return sorted(all_channels, key=lambda c: c["name"].lower())

    return []


def main():
    parser = argparse.ArgumentParser(
        description="Sync YouTube subscriptions to subscriptions.json."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--browser", metavar="NAME", choices=BROWSERS,
        help=f"Read cookies directly from browser: {', '.join(BROWSERS)}",
    )
    source.add_argument(
        "--cookies", metavar="FILE",
        help="Path to a Netscape-format cookies.txt file",
    )
    parser.add_argument(
        "--output", default="subscriptions.json", metavar="FILE",
        help="Output path (default: subscriptions.json)",
    )
    args = parser.parse_args()

    if args.cookies:
        cookies_path = Path(args.cookies)
        if not cookies_path.is_file():
            print(f"‼ Cookies file not found: {cookies_path}", file=sys.stderr)
            sys.exit(1)
        cookies = cookies_from_file(cookies_path)
    else:
        cookies = cookies_from_browser(args.browser)

    print("Fetching subscriptions from YouTube…")
    auth_names = auth_cookie_names_present(cookies)
    if not auth_names:
        print(
            "⚠ No YouTube auth cookies were found in that browser profile.",
            file=sys.stderr,
        )
        print(
            "  Try a different browser, or export cookies.txt and use --cookies.",
            file=sys.stderr,
        )
    else:
        print(f"  Using auth cookies: {', '.join(auth_names)}")
    channels = fetch_subscriptions(cookies)

    if not channels:
        if args.browser == "safari":
            print(
                "‼ Safari did not return any subscription channels. "
                "Export cookies.txt and retry with --cookies.",
                file=sys.stderr,
            )
        else:
            print(
                "‼ No channels found — are you logged in to YouTube in that browser?",
                file=sys.stderr,
            )
        sys.exit(1)

    out = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"✔ {len(channels)} channels written to {output_path}")


if __name__ == "__main__":
    main()
