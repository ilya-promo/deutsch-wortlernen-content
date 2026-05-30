#!/usr/bin/env python3
"""
Обогащает каждый level JSON Perfekt-примером для каждого глагола.
Запуск:  ANTHROPIC_API_KEY=... python3 scripts/generate_perfekt_examples.py [a1 a2 ...]

Если уровни не указаны — обрабатываются все 6.
Пропускает глаголы у которых example_perfekt_de/ru уже заполнены.
"""
import json
import os
import sys
import time
from pathlib import Path
from anthropic import Anthropic

LEVELS_ALL = ["a1", "a2", "b1", "b2", "c1", "c2"]
MODEL = "claude-sonnet-4-6"

PROMPT_TEMPLATE = """You generate German learning examples.

Word (Infinitiv): {lemma}
Russian translations: {translations}
Existing Präsens example: "{example_de}" — "{example_ru}"
Partizip II: {partizip_ii}

Generate ONE natural sentence in German using "{lemma}" in Perfekt tense
(auxiliary "haben" or "sein" + "{partizip_ii}"), plus its Russian translation.

Rules:
- Subject: ich / du / er / sie / wir / sie (simple A1-friendly)
- Length: 4-8 words in German
- Russian translation must sound natural in past tense
- Pick the CORRECT auxiliary (sein for motion/state-change verbs; haben for the rest)
- Avoid mirroring the structure of the existing example
- Output STRICT JSON ONLY: {{"de": "...", "ru": "..."}}"""


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    levels = sys.argv[1:] if len(sys.argv) > 1 else LEVELS_ALL
    levels = [l.lower() for l in levels]
    for l in levels:
        if l not in LEVELS_ALL:
            print(f"ERROR: unknown level '{l}'", file=sys.stderr)
            sys.exit(1)

    client = Anthropic(api_key=api_key)
    root = Path(__file__).resolve().parent.parent

    total_done = 0
    total_skipped = 0
    total_failed = []
    total_cost_estimate = 0.0

    for level in levels:
        path = root / f"{level}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        verbs = [w for w in data if w.get("pos") == "verb" and w.get("verb_forms")]
        print(f"=== {level}: {len(verbs)} verbs ===", flush=True)
        changed = 0
        for w in verbs:
            vf = w["verb_forms"]
            if vf.get("example_perfekt_de") and vf.get("example_perfekt_ru"):
                total_skipped += 1
                continue

            prompt = PROMPT_TEMPLATE.format(
                lemma=w["lemma"],
                partizip_ii=vf.get("partizip_ii", ""),
                translations=", ".join(w.get("translations", [])),
                example_de=w.get("example_de", ""),
                example_ru=w.get("example_ru", ""),
            )

            try:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text.strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    text = "\n".join(line for line in lines if not line.startswith("```"))
                parsed = json.loads(text)
                vf["example_perfekt_de"] = parsed["de"].strip()
                vf["example_perfekt_ru"] = parsed["ru"].strip()
                changed += 1
                total_done += 1
                # rough cost: Sonnet 4.6 = $3/M input, $15/M output
                in_tok = resp.usage.input_tokens
                out_tok = resp.usage.output_tokens
                total_cost_estimate += in_tok * 3e-6 + out_tok * 15e-6
                print(f"  ok {w['lemma']:20s} -> {parsed['de']}", flush=True)
            except Exception as e:
                total_failed.append((w["id"], w["lemma"], str(e)))
                print(f"  FAIL {w['lemma']}: {e}", file=sys.stderr, flush=True)

            time.sleep(0.05)

        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  saved {changed} updates to {path.name}", flush=True)

    print(f"\n=== Done ===", flush=True)
    print(f"  New entries:    {total_done}", flush=True)
    print(f"  Skipped:        {total_skipped}", flush=True)
    print(f"  Failed:         {len(total_failed)}", flush=True)
    print(f"  Estimated cost: ${total_cost_estimate:.2f}", flush=True)
    if total_failed:
        print("\nFailed items (first 20):")
        for fid, fl, fe in total_failed[:20]:
            print(f"  {fid:12s} {fl:25s} {fe}", file=sys.stderr)


if __name__ == "__main__":
    main()
