import os, re, sys

sys.stdout.reconfigure(encoding='utf-8')

EMOJI_REGEX = re.compile(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U0001F000-\U0001F2FF]')
TYPO_PICTO_REGEX = re.compile(r'[‹›←→↑↓✓✔✕✖▸▾▼▲●■◆▪↺⚡]')
HTML_ENTITY_REGEX = re.compile(r'&#(?:x[0-9a-fA-F]+|[0-9]+);|&(?:check|times|rarr|larr|uarr|darr|bull|hellip);')

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
hits = []

for dirpath, dirnames, filenames in os.walk(root_dir):
    if any(p in dirpath for p in ['.git', '.venv', 'node_modules', '__pycache__', 'scratch']):
        continue
    for fname in filenames:
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ['.html', '.css', '.js', '.py', '.md']:
            continue
        filepath = os.path.join(dirpath, fname)
        rel_path = os.path.relpath(filepath, root_dir)
        # Allowlist: sample scene data and the checker itself
        if 'sample_scene.json' in rel_path or 'scene.json' in rel_path or 'check_no_emoji.py' in rel_path or 'audit_emoji.py' in rel_path:
            continue
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    found_in_line = []
                    for m in EMOJI_REGEX.finditer(line):
                        found_in_line.append(('EMOJI', m.group(), hex(ord(m.group()))))
                    for m in TYPO_PICTO_REGEX.finditer(line):
                        found_in_line.append(('TYPOGRAPHIC', m.group(), hex(ord(m.group()))))
                    for m in HTML_ENTITY_REGEX.finditer(line):
                        found_in_line.append(('HTML_ENTITY', m.group(), m.group()))
                    for kind, char, codepoint in found_in_line:
                        hits.append({
                            'file': rel_path.replace('\\', '/'),
                            'line': line_no,
                            'kind': kind,
                            'char': char,
                            'codepoint': codepoint,
                            'content': line.strip()
                        })
        except Exception as e:
            pass

print(f"=== TOTAL HITS: {len(hits)} ===")
for h in hits:
    print(f"{h['file']}:{h['line']} [{h['kind']}] {h['char']} ({h['codepoint']}) => {h['content']}")
