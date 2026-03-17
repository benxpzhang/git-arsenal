#!/usr/bin/env python3
"""
Prepare wiki text for embedding.

- Reads DeepWiki overviews and cleans them
- Falls back to GitHub description for repos without DeepWiki
- Outputs wiki_texts.jsonl aligned with repos_meta.jsonl order
"""
import json
import re
import argparse
from pathlib import Path


def clean_overview(overview: str, max_chars: int = 800) -> str:
    """Extract clean descriptive text from DeepWiki overview markdown."""
    text = overview

    text = re.sub(r'<details>.*?</details>', '', text, flags=re.DOTALL)
    text = re.sub(r'<CgxTip>.*?</CgxTip>', '', text, flags=re.DOTALL)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'^#+\s.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\**(?:Sources?|来源)\**:?.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', text)
    # Remove file references like filename.md:1-868
    text = re.sub(r'\w+\.\w+:\d+-\d+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'\1', text)

    lines = [l.strip() for l in text.split('\n')]
    paragraphs = []
    current = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(' '.join(current))
            current = []
    if current:
        paragraphs.append(' '.join(current))

    good = []
    for p in paragraphs:
        if len(p) < 40:
            continue
        if re.match(
            r'^(This (document|page|overview|wiki) (covers|provides|is intended)'
            r'|For (detailed|specific|more|a quick|installation|setup|information))',
            p, re.IGNORECASE,
        ):
            continue
        if re.search(r'(see|refer to)\s+(the )?(following|respective|dedicated)', p, re.IGNORECASE) and '#' in p:
            continue
        if p.count('#') > 2:
            continue
        good.append(p)

    result = ''
    for p in good:
        if len(result) + len(p) + 2 > max_chars:
            if not result:
                result = p[:max_chars]
            break
        result += p + '\n\n'

    return result.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deepwiki', type=str,
                        default='/data/workspace/code/github_repos/deepwiki/deepwiki_overviews.jsonl')
    parser.add_argument('--meta', type=str,
                        default=str(Path(__file__).resolve().parent.parent / 'packages/api/data/repos_meta.jsonl'))
    parser.add_argument('--output', type=str,
                        default=str(Path(__file__).resolve().parent.parent / 'packages/api/data/wiki_texts.jsonl'))
    args = parser.parse_args()

    # Load DeepWiki overviews (only ok status)
    print("Loading DeepWiki overviews...")
    dw_map: dict[str, str] = {}
    with open(args.deepwiki, 'r') as f:
        for line in f:
            obj = json.loads(line)
            if obj.get('status') == 'ok' and obj.get('overview'):
                cleaned = clean_overview(obj['overview'])
                if cleaned:
                    dw_map[obj['full_name']] = cleaned
    print(f"  DeepWiki cleaned: {len(dw_map):,} repos")

    # Process repos_meta in order, output wiki_texts aligned
    print("Processing repos_meta...")
    total = 0
    dw_used = 0
    desc_used = 0
    empty = 0

    with open(args.meta, 'r') as fin, open(args.output, 'w') as fout:
        for line in fin:
            try:
                repo = json.loads(line)
            except json.JSONDecodeError:
                fout.write(json.dumps({"full_name": "", "wiki_text": ""}, ensure_ascii=False) + '\n')
                total += 1
                continue

            fn = repo.get('full_name', '')
            wiki_text = ''

            if fn in dw_map:
                wiki_text = dw_map[fn]
                dw_used += 1
            else:
                desc = repo.get('description', '') or ''
                if desc:
                    wiki_text = desc
                    desc_used += 1
                else:
                    empty += 1

            fout.write(json.dumps({"full_name": fn, "wiki_text": wiki_text}, ensure_ascii=False) + '\n')
            total += 1

    print(f"Done! Total: {total:,}")
    print(f"  DeepWiki: {dw_used:,} ({dw_used/total*100:.1f}%)")
    print(f"  Description fallback: {desc_used:,} ({desc_used/total*100:.1f}%)")
    print(f"  Empty: {empty:,} ({empty/total*100:.1f}%)")
    print(f"Output: {args.output}")


if __name__ == '__main__':
    main()
