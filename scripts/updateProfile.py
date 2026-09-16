"""
Daily profile updater.

Calls an LLM (Llama 3.3 on Groq) to write a fresh one-liner for the README,
then swaps it into the AI-note section between the marker comments.

This is intentionally small and dependency-free (uses only the stdlib) so the
GitHub Action stays fast and never breaks on a missing package.

Env vars:
  GROQ_API_KEY  - required. Free key from https://console.groq.com/keys
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

README_PATH = "README.md"
START = "<!--START_SECTION:ai-note-->"
END = "<!--END_SECTION:ai-note-->"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq deprecated llama-3.3-70b-versatile on 2026-06-17; gpt-oss-120b is the
# recommended replacement. See https://console.groq.com/docs/models for the
# current list if this ever stops working.
MODEL = "openai/gpt-oss-120b"

SYSTEM = (
    "You write a single short line (max ~18 words) for Tharun's GitHub profile. "
    "Tharun is a Full Stack & AI Engineer who builds RAG systems, LLM agents, and "
    "eval harnesses with React/Next.js/Node/NestJS and Python. "
    "The line should sound like a real engineer's daily thought about building AI "
    "or full-stack software - specific, a little opinionated, never corporate or "
    "hype. No hashtags, no emojis, no quotation marks. Just the sentence."
)
USER = "Write today's line."

FALLBACK = "Building AI features the honest way: measure quality before you trust it."


def generate_line() -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        print("No GROQ_API_KEY set; using fallback line.", file=sys.stderr)
        return FALLBACK

    payload = json.dumps(
        {
            "model": MODEL,
            "temperature": 0.9,
            # gpt-oss is a reasoning model: it spends tokens "thinking" before the
            # answer. Keep reasoning low and leave plenty of room, or the visible
            # content comes back empty (truncated mid-reasoning).
            "reasoning_effort": "low",
            "max_completion_tokens": 1024,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER},
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Cloudflare in front of Groq returns 403 (error 1010) for the default
            # "Python-urllib/x" agent, so present a normal browser-like User-Agent.
            "User-Agent": "Mozilla/5.0 (compatible; profile-updater/1.0)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = data["choices"][0]
        content = (choice.get("message", {}).get("content") or "").strip()
        # Defensively drop any <think>...</think> block some reasoning models emit.
        content = re.sub(r"(?is)<think>.*?</think>", "", content).strip()
        # Keep only the first non-empty line, unquoted.
        line = next((l.strip().strip('"').strip() for l in content.splitlines() if l.strip()), "")
        if not line:
            print(
                f"Empty content (finish_reason={choice.get('finish_reason')}); "
                f"using fallback line.",
                file=sys.stderr,
            )
            return FALLBACK
        return line
    except urllib.error.HTTPError as exc:
        # Surface the real API error (e.g. decommissioned model, bad key) in the log.
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        print(f"LLM HTTP {exc.code}: {body}; using fallback line.", file=sys.stderr)
        return FALLBACK
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"LLM call failed ({exc}); using fallback line.", file=sys.stderr)
        return FALLBACK


def build_block(line: str) -> str:
    return (
        f"{START}\n"
        f"> _“{line}”_\n\n"
        f"<sub>\U0001f7e2 auto-generated · powered by an LLM on Groq · "
        f"updates daily via GitHub Actions</sub>\n"
        f"{END}"
    )


def main() -> int:
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    line = generate_line()
    new_block = build_block(line)

    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(readme):
        print("Marker section not found in README.md", file=sys.stderr)
        return 1

    updated = pattern.sub(lambda _: new_block, readme)

    if updated == readme:
        print("No change.")
        return 0

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"Updated AI note: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
