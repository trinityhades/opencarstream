#!/usr/bin/env python3
"""
Populate YouTube channel logos for subscriptions in subscriptions.json.
Scrapes the public channel page HTML to extract the 'og:image' tag.
Saves progress in-place after each channel to allow interruption and resumption.
"""

import os
import re
import sys
import json
import time
import requests
from pathlib import Path

DEFAULT_PATHS = ["config/subscriptions.json", "subscriptions.json"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_logo_url(channel_url: str) -> str | None:
    try:
        resp = requests.get(channel_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        
        # Search for og:image meta tag
        match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
        if match:
            return match.group(1).strip()
            
        # Fallback to image_src
        match2 = re.search(r'<link rel="image_src" href="([^"]+)"', resp.text)
        if match2:
            return match2.group(1).strip()
            
    except Exception as e:
        print(f"\n  Error fetching {channel_url}: {e}", file=sys.stderr)
        
    return None

def process_file(file_path: Path, force: bool = False):
    if not file_path.is_file():
        print(f"File not found: {file_path}")
        return

    print(f"\nProcessing subscriptions file: {file_path}")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        return

    channels = data.get("channels", [])
    if not channels:
        print("No channels found in this file.")
        return

    total = len(channels)
    updated_count = 0
    skipped_count = 0

    print(f"Found {total} channels. Fetching logos...")
    
    try:
        for idx, channel in enumerate(channels, 1):
            name = channel.get("name", "Unknown")
            url = channel.get("url", "")
            
            if not url:
                continue
                
            # If it already has a logo and we are not forcing, skip
            if channel.get("logo") and not force:
                skipped_count += 1
                continue

            print(f"[{idx}/{total}] Fetching logo for '{name}'...", end="", flush=True)
            
            logo_url = fetch_logo_url(url)
            if logo_url:
                channel["logo"] = logo_url
                updated_count += 1
                print(" Success!")
                
                # Write back immediately to prevent progress loss
                file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                print(" Failed (not found or error).")
                
            # Sleep slightly to prevent hitting YouTube rate limits
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\nSync interrupted by user. Progress saved.")
        sys.exit(0)

    print(f"\nFinished: {updated_count} logos updated, {skipped_count} skipped (already had logos).")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Populate channel logos in subscriptions.json.")
    parser.add_argument("--file", help="Path to subscriptions.json file")
    parser.add_argument("--force", action="store_true", help="Overwrite existing logos")
    args = parser.parse_args()

    if args.file:
        process_file(Path(args.file), args.force)
    else:
        found_any = False
        for path_str in DEFAULT_PATHS:
            p = Path(path_str)
            if p.is_file():
                process_file(p, args.force)
                found_any = True
        if not found_any:
            print("No subscriptions.json file found in default locations. Specify path with --file.")

if __name__ == "__main__":
    main()
