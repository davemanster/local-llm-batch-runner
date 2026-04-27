"""
batch_runner.py -- Resumable multi-node LLM batch processor.

Distributes a folder of input files across one or more local LLM inference
endpoints simultaneously. Each file is claimed atomically from a shared queue,
run through a configurable multi-stage pipeline, and written to a shared output
directory. Interrupted runs resume automatically on the next execution.

Usage:
    python batch_runner.py              # run all configured nodes
    python batch_runner.py --node 0    # run only the first node
    python batch_runner.py --node 1    # run only the second node

Stopping:
    Ctrl+C          graceful -- finishes current LLM call, then stops
    Ctrl+C again    hard kill immediately
    Drop STOP file  same as Ctrl+C (useful when terminal is not accessible)
"""

import argparse
import json
import os
import queue
import re
import signal
import threading
import time
import requests
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config -- edit these to match your setup
# ---------------------------------------------------------------------------

NODES = [
    {
        "label":    "node_0",
        "endpoint": "http://10.0.0.10:1234/v1/chat/completions",
        "model":    "your-model-name",
    },
    {
        "label":    "node_1",
        "endpoint": "http://10.0.0.11:1234/v1/chat/completions",
        "model":    "your-model-name",
    },
]

# Labels to run. All by default. Override via --node flag.
ACTIVE_NODES = [n["label"] for n in NODES]

# Limit run to specific files by name. Empty set = process all.
ONLY_FILES: set = set()

INPUT_DIR  = Path("input/")    # folder of files to process
OUTPUT_DIR = Path("output/")   # shared output directory

INPUT_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".txt"}

MAX_TOKENS  = 32000
LLM_RETRIES = 3

# Kill switch -- set by Ctrl+C or by dropping a file named STOP in this directory.
STOP_EVENT = threading.Event()
KILL_FILE  = Path("STOP")

# ---------------------------------------------------------------------------
# Stage prompts -- replace these with your task-specific instructions.
#
# The three-stage pattern:
#   Stage 1 (high temp ~0.8): Liberal interpretation. Feed the raw input and
#       ask the model to describe, narrate, or freely interpret it. Don't ask
#       for structure here. The goal is richness.
#   Stage 2 (low temp ~0.4): Strict extraction. Feed the Stage 1 output and
#       ask the model to extract structured fields (typically JSON) from it.
#       The model never sees the raw input -- only the Stage 1 description.
#   Stage 3 (medium temp ~0.6): Optional validation/smoothing. Feed the Stage 2
#       JSON and ask the model to check it for consistency or apply business rules.
#
# See examples/ for ready-to-use prompt sets for common tasks.
# ---------------------------------------------------------------------------

STAGE1_SYSTEM = """
[REPLACE THIS with your Stage 1 prompt]

Example (image tagging):
You are a detailed image analyst. Describe everything visible in this image --
objects, colors, composition, text, context, mood. Be thorough and specific.
Do NOT produce JSON. Write a rich prose description.
""".strip()

STAGE2_SYSTEM = """
[REPLACE THIS with your Stage 2 prompt]

Example (image tagging):
You are converting a prose image description into structured metadata.
Given the description in the user message, produce a JSON object with these fields:
{
  "category": "string -- the primary subject category",
  "dominant_colors": ["list of color strings"],
  "contains_text": true|false,
  "subject_count": integer,
  "scene_type": "indoor|outdoor|abstract|other",
  "keywords": ["list of descriptive keywords"],
  "mood": "string -- overall mood or tone"
}
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()

STAGE3_SYSTEM = """
[REPLACE THIS with your Stage 3 prompt, or remove Stage 3 entirely if not needed]

Example (image tagging):
Review this JSON metadata object. Check for internal consistency:
- If scene_type is "outdoor", dominant_colors should not include "fluorescent"
- If subject_count is 0, keywords should not reference people
- Ensure all fields are present and non-empty
Return the corrected JSON. Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()

# ---------------------------------------------------------------------------
# Output classification -- how to organize files into subfolders.
# Replace this with logic that reads your Stage 2/3 JSON output.
# ---------------------------------------------------------------------------

def classify_output(parsed: dict) -> str:
    """Return a subfolder name for this output based on its content."""
    return parsed.get("category", "uncategorized").lower().replace(" ", "_")

# ---------------------------------------------------------------------------
# Kill switch helpers
# ---------------------------------------------------------------------------

def stopped() -> bool:
    if STOP_EVENT.is_set():
        return True
    if KILL_FILE.exists():
        STOP_EVENT.set()
        return True
    return False


def _handle_sigint(signum, frame):
    if not STOP_EVENT.is_set():
        print("\n[STOP] Ctrl+C -- finishing current LLM call, then stopping.", flush=True)
        print("[STOP] Press Ctrl+C AGAIN to hard-kill immediately.", flush=True)
        STOP_EVENT.set()
        try:
            KILL_FILE.write_text("stop\n")
        except Exception:
            pass
    else:
        print("\n[STOP] Hard kill -- terminating now.", flush=True)
        os._exit(1)

# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

def strip_thinking(text: str) -> str:
    """Strip internal <thinking> blocks some models emit before their response."""
    if not text:
        return text
    text = re.sub(r'<think(?:ing)?>[\s\S]*?</think(?:ing)?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\|start_thinking\|>[\s\S]*?<\|end_thinking\|>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*thinking:[\s\S]*?\n\n', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[thinking\][\s\S]*?\[/thinking\]', '', text, flags=re.IGNORECASE)
    return text.strip()


def call_llm(endpoint: str, model: str, messages: list,
             temperature: float = 0.8, max_tokens: int = MAX_TOKENS) -> str:
    last_err = None
    for attempt in range(LLM_RETRIES):
        try:
            resp = requests.post(
                endpoint,
                json={
                    "model":       model,
                    "messages":    messages,
                    "temperature": temperature,
                    "max_tokens":  max_tokens,
                    "stream":      False,
                },
                timeout=None,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            if not raw:
                raise ValueError("Empty content in LLM response")
            return strip_thinking(raw)
        except Exception as e:
            last_err = e
            if attempt < LLM_RETRIES - 1:
                time.sleep(5 * (attempt + 1))
    raise last_err

# ---------------------------------------------------------------------------
# JSON parsing -- handles common LLM formatting issues
# ---------------------------------------------------------------------------

def parse_json_output(raw: str) -> dict:
    cleaned = strip_thinking(raw)
    cleaned = re.sub(r'```json\s*|```', '', cleaned).strip()
    first = cleaned.find('{')
    last  = cleaned.rfind('}')
    if first == -1 or last == -1:
        raise ValueError("No JSON object found in LLM response")
    json_str = cleaned[first:last + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Repair common issues: smart quotes, trailing commas
        repaired = json_str
        repaired = repaired.replace('“', '"').replace('”', '"')
        repaired = repaired.replace('‘', "'").replace('’', "'")
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        return json.loads(repaired)

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')[:60] or "output"


def unique_stem(folder: Path, stem: str, ext: str) -> str:
    if not (folder / (stem + ext)).exists():
        return stem
    counter = 2
    while (folder / f"{stem}_{counter}{ext}").exists():
        counter += 1
    return f"{stem}_{counter}"

# ---------------------------------------------------------------------------
# Tracking files
# ---------------------------------------------------------------------------

def read_lines_set(path: Path) -> set:
    if not path.exists():
        return set()
    return {l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def read_failed_set(path: Path) -> set:
    if not path.exists():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(" | ")
        if len(parts) >= 2:
            result.add(parts[1].strip())
    return result


def append_line(path: Path, line: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_line(status: str, filename: str, detail: str, elapsed: float):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    m, s = divmod(int(elapsed), 60)
    append_line(OUTPUT_DIR / "run_log.txt",
                f"{ts} | {status:<4} | {filename:<50} | {detail} | {m}m {s:02d}s")

# ---------------------------------------------------------------------------
# Optional post-processing hook
# Replace or remove this if you don't need post-processing (e.g. thumbnail
# creation, database insertion, file format conversion, etc.)
# ---------------------------------------------------------------------------

def post_process(parsed: dict, output_stem: Path, source_path: Path):
    """
    Called after Stage 3 completes, before the item is marked done.
    Failures here are non-fatal -- the item is still marked completed.

    parsed      -- the final parsed JSON dict
    output_stem -- Path to the output file without extension (e.g. output/category/slug)
    source_path -- Path to the original input file
    """
    pass  # Replace with your post-processing logic

# ---------------------------------------------------------------------------
# Worker (one per endpoint -- pulls from shared queue)
# ---------------------------------------------------------------------------

def worker(node: dict, file_queue: queue.Queue, lock: threading.Lock,
           done_path: Path, fail_path: Path):
    label    = node["label"]
    endpoint = node["endpoint"]
    model    = node["model"]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    while not STOP_EVENT.is_set():
        try:
            file_path = file_queue.get(timeout=2)
        except queue.Empty:
            break

        file_queue.task_done()

        with lock:
            if file_path.name in read_lines_set(done_path) | read_failed_set(fail_path):
                continue

        t_start   = time.time()
        remaining = file_queue.qsize()
        print(f"[{label}] [{remaining} left] {file_path.name}", flush=True)

        try:
            # ---------------------------------------------------------------
            # Build the user message for Stage 1.
            # For text files: just read the content.
            # For images: encode as base64 data URL (requires a vision model).
            # Adjust this block to match your input type.
            # ---------------------------------------------------------------
            ext = file_path.suffix.lower()
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                import base64
                mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"
                b64  = base64.b64encode(file_path.read_bytes()).decode()
                user_content = [
                    {"type": "text",      "text": "Process this image according to your instructions."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]
            else:
                user_content = file_path.read_text(encoding="utf-8", errors="replace")

            # Stage 1 -- liberal interpretation
            print(f"[{label}]   Stage 1...", flush=True)
            msgs1    = [{"role": "system", "content": STAGE1_SYSTEM},
                        {"role": "user",   "content": user_content}]
            stage1   = call_llm(endpoint, model, msgs1, temperature=0.8)
            print(f"[{label}]   Stage 1 done ({len(stage1):,} chars)", flush=True)

            if stopped():
                break

            # Stage 2 -- strict extraction
            print(f"[{label}]   Stage 2 (JSON)...", flush=True)
            msgs2    = [{"role": "system", "content": STAGE2_SYSTEM},
                        {"role": "user",   "content": stage1}]
            stage2   = call_llm(endpoint, model, msgs2, temperature=0.4)
            print(f"[{label}]   Stage 2 done ({len(stage2):,} chars)", flush=True)

            if stopped():
                break

            # Stage 3 -- validation / smoothing (remove if not needed)
            print(f"[{label}]   Stage 3 (validation)...", flush=True)
            msgs3    = [{"role": "system", "content": STAGE3_SYSTEM},
                        {"role": "user",   "content": stage2}]
            stage3   = call_llm(endpoint, model, msgs3, temperature=0.6)
            print(f"[{label}]   Stage 3 done ({len(stage3):,} chars)", flush=True)

            # Parse JSON output
            parsed   = parse_json_output(stage3)

            # Organize into output subfolder by classification
            category = classify_output(parsed)
            out_dir  = OUTPUT_DIR / category
            out_dir.mkdir(exist_ok=True)

            stem     = unique_stem(out_dir, slug(file_path.stem), ".json")
            out_path = out_dir / (stem + ".json")
            out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")

            # Optional post-processing (non-fatal)
            try:
                post_process(parsed, out_dir / stem, file_path)
            except Exception as pe:
                print(f"[{label}]   Post-process FAILED (non-fatal): {pe}", flush=True)
                log_line("WARN", file_path.name, f"post_process: {str(pe)[:80]}", time.time() - t_start)

            elapsed = time.time() - t_start
            with lock:
                append_line(done_path, file_path.name)
            log_line("DONE", file_path.name, f"{category}/{stem}", elapsed)
            print(f"[{label}]   [OK] {category}/{stem}  ({int(elapsed)}s)", flush=True)

        except Exception as e:
            elapsed = time.time() - t_start
            msg = str(e)
            log_line("FAIL", file_path.name, msg[:120], elapsed)
            with lock:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                append_line(fail_path, f"{ts} | {file_path.name} | {msg}")
            print(f"[{label}]   [FAIL] {msg}", flush=True)

    print(f"[{label}] Worker exiting.", flush=True)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multi-node LLM batch processor.")
    parser.add_argument("--node", type=int, default=None,
                        help="Run only one node by index (0-based). Omit to run all.")
    args = parser.parse_args()

    global ACTIVE_NODES
    if args.node is not None:
        if args.node >= len(NODES):
            print(f"Error: --node {args.node} is out of range ({len(NODES)} nodes configured).")
            return
        ACTIVE_NODES = [NODES[args.node]["label"]]

    if KILL_FILE.exists():
        KILL_FILE.unlink()
        print("[STOP] Removed leftover STOP file from previous run.", flush=True)

    signal.signal(signal.SIGINT, _handle_sigint)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    active    = [n for n in NODES if n["label"] in ACTIVE_NODES]
    done_path = OUTPUT_DIR / "completed.txt"
    fail_path = OUTPUT_DIR / "failed.txt"

    all_files = sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in INPUT_EXTS
    )
    completed = read_lines_set(done_path)
    failed    = read_failed_set(fail_path)
    skip      = completed | failed
    todo      = [p for p in all_files
                 if p.name not in skip and (not ONLY_FILES or p.name in ONLY_FILES)]

    print(f"Batch starting -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"Input:  {INPUT_DIR.resolve()}", flush=True)
    print(f"Output: {OUTPUT_DIR.resolve()}", flush=True)
    print(f"Nodes:  {', '.join(n['label'] + ' (' + n['endpoint'] + ')' for n in active)}", flush=True)
    print(f"Queue:  {len(todo)} files  |  {len(completed)} already done  |  {len(failed)} previously failed", flush=True)
    print(f"PID:    {os.getpid()}  (taskkill /PID {os.getpid()} /F  or  kill -9 {os.getpid()})", flush=True)
    print(f"Ctrl+C = graceful stop  |  drop STOP file = same  |  Ctrl+C twice = hard kill", flush=True)

    if not todo:
        print("Nothing to process.", flush=True)
        return

    file_queue = queue.Queue()
    for f in todo:
        file_queue.put(f)

    lock    = threading.Lock()
    threads = [
        threading.Thread(target=worker,
                         args=(node, file_queue, lock, done_path, fail_path),
                         name=node["label"], daemon=False)
        for node in active
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\nBatch complete -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
