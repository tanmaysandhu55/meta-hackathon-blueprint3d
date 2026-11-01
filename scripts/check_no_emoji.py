#!/usr/bin/env python3
"""
scripts/check_no_emoji.py
Scans the project codebase to ensure NO emojis or decorative pictographs exist in UI/code.
Allowlist: scene.json sample data.
Returns exit code 0 if clean, 1 if any hits found.
"""
import os
import re
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Emojis regex with Unicode ranges
EMOJI_REGEX = re.compile(
    r'[\U0001F300-\U0001FAFF'  # Misc Symbols & Pictographs, Supplemental, etc.
    r'\U00002600-\U000027BF'    # Misc Symbols, Dingbats (sun, check, lightning, etc.)
    r'\U00002B00-\U00002BFF'    # Misc Symbols and Arrows
    r'\U0000FE0F\U0000200D'     # Variation Selectors, ZWJ
    r'\U0001F000-\U0001F2FF]'   # Enclosed Ideographic, etc.
)

# Decorative typographic symbols & pictographs
TYPOGRAPHIC_REGEX = re.compile(r'[‹›←→↑↓✓✔✕✖▸▾▼▲●■◆▪↺⚡]')

# Decorative HTML entities (excluding standard XML/HTML &amp;, &lt;, &gt;, &quot;, &#39;)
DECORATIVE_ENTITY_REGEX = re.compile(
    r'&#(?:x[0-9a-fA-F]+|[0-9]+);|&(?:check|times|rarr|larr|uarr|darr|bull|hellip);'
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

EXCLUDED_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', 'scratch'}
SCANNED_EXTENSIONS = {'.html', '.css', '.js', '.py', '.md'}

ALLOWLIST_PATTERNS = [
    'samples/sample_scene.json',
    'samples/two_story_demo_scene.json',
    'scripts/check_no_emoji.py',
    'scripts/audit_emoji.py',
    'test_scene_schema.py',  # schema tests checking data
]

def is_allowlisted(rel_path):
    rel_path_fwd = rel_path.replace('\\', '/')
    for pattern in ALLOWLIST_PATTERNS:
        if pattern in rel_path_fwd:
            return True
    return False

def check_project():
    hits = []
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        # Skip excluded dirs in-place
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SCANNED_EXTENSIONS:
                continue
            filepath = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(filepath, PROJECT_ROOT).replace('\\', '/')
            if is_allowlisted(rel_path):
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line_no, line in enumerate(f, 1):
                        for m in EMOJI_REGEX.finditer(line):
                            hits.append((rel_path, line_no, 'EMOJI', m.group(), line.strip()))
                        for m in TYPOGRAPHIC_REGEX.finditer(line):
                            hits.append((rel_path, line_no, 'TYPOGRAPHIC', m.group(), line.strip()))
                        for m in DECORATIVE_ENTITY_REGEX.finditer(line):
                            # Allow standard &#39; if it occurs
                            if m.group() == '&#39;':
                                continue
                            hits.append((rel_path, line_no, 'HTML_ENTITY', m.group(), line.strip()))
            except Exception as e:
                print(f"Error reading {rel_path}: {e}", file=sys.stderr)

    return hits

if __name__ == '__main__':
    hits = check_project()
    if hits:
        print(f"FAILED: Found {len(hits)} emoji/decorative pictograph hit(s):")
        for file, line, kind, char, content in hits:
            codepoint = hex(ord(char[0])) if char else ""
            print(f"  {file}:{line} [{kind}] {char} ({codepoint}) -> {content[:80]}")
        sys.exit(1)
    else:
        print("PASS: Zero emojis or decorative pictographs found across the project.")
        sys.exit(0)
