# local-llm-batch-runner

A Python tool for distributing a batch of LLM jobs across multiple local inference servers in parallel. Resumable, no database, no coordination service. `requests` is the only dependency. I did not easily find a tool that fit my use case so... here this is.

## The problem

Local LLM tools like LM Studio and Ollama are good for one request at a time. Neither has anything built in for distributing a folder of work across multiple machines. If you have two boxes with GPUs and a thousand images to caption, there's no clean way to point both of them at the same queue and have them share the load.

Cloud APIs handle this with concurrency, but they cost money, send your data offsite, and ratelimit you. If you already own the hardware, use it.

## Where this came from

I built this for a Flux LoRA I was training on about 1500 reference images. I needed a `.txt` caption file sitting next to each image for kohya_ss to read at training time. Running that on one GPU was going to take most of a weekend. I had a second machine with another GPU sitting idle, so I wrote a small queue distributor that lets two LM Studio instances share the same folder and resume cleanly if either one dies mid-run.

The pattern turned out to be useful for more than just captioning. I stripped the LoRA-specific prompts out and kept the runner generic. The captioning prompts are still in `examples/ai_image_gen_finetune.py` if that's what you're doing too.

## Quick start: captioning a dataset for fine-tuning

This is what the tool was built for. Point it at a folder of training images and it produces a `.txt` caption file next to each one — the format kohya_ss, ai-toolkit, and diffusion-pipe expect.

```bash
git clone https://github.com/davemanster/local-llm-batch-runner
cd local-llm-batch-runner
pip install requests
```

Open `examples/ai_image_gen_finetune.py` and set your trigger word:

```python
TRIGGER_WORD = "mysubject"  # unique token for this subject or style; "" for none
```

Open `batch_runner.py` and edit the config block at the top:

```python
NODES = [
    {"label": "node_a", "endpoint": "http://10.0.0.10:1234/v1/chat/completions", "model": "your-model"},
    {"label": "node_b", "endpoint": "http://10.0.0.11:1234/v1/chat/completions", "model": "your-model"},
]

INPUT_DIR  = Path("/path/to/your/dataset")  # folder of images to caption
OUTPUT_DIR = Path("output/")                # where JSON + logs land
```

Copy everything from `examples/ai_image_gen_finetune.py` into `batch_runner.py` — the `TRIGGER_WORD`, the three `STAGE*_SYSTEM` strings, `classify_output`, and `post_process`. Then run:

```bash
python batch_runner.py
```

Both nodes start working the same queue. When each image finishes, the caption is written directly into your dataset folder:

```
dataset/
  img001.png
  img001.txt    <-- written automatically, ready for kohya_ss
  img002.png
  img002.txt
  ...
```

Images flagged as low quality or watermarked go to `output/review/` without a `.txt` file so you can look at them before deciding whether to train on them. Everything else goes to `output/use/`.

Hit Ctrl+C any time. The next run picks up where you left off.

## What it does

**Shared queue across nodes.** One in-memory `queue.Queue` feeds every worker. Items are claimed atomically, so nothing is processed twice even when two workers race for the queue. Adding a third node is one more dict in the config.

**Three-stage captioning pipeline.** Each image runs through three sequential LLM calls. Stage 1 asks the model to describe everything it sees — subject, pose, clothing, setting, lighting, framing — in plain prose. Stage 2 takes that description and produces a structured training caption: a 1–3 sentence natural-language string starting with your trigger word. Stage 3 validates the result, checks that the trigger is present, trims captions that are too long or short, and sets quality flags for blurry or watermarked images. LLMs do better when you split "describe the image" and "write a valid caption" into separate calls rather than asking for both at once.

**Writes .txt caption files into your dataset.** After each image completes, the caption is written as a `.txt` file next to the source image — the format kohya_ss, ai-toolkit, and diffusion-pipe read at training time. You don't need to run a second script or touch the output directory.

**Flags low-quality images for review.** Images the model marks as blurry, low-resolution, or watermarked are sorted into `output/review/` without a `.txt` file. Everything clean goes to `output/use/`. You decide what to do with the flagged ones before training.

**Resumable.** The runner reads `completed.txt` and `failed.txt` from the output directory at startup and skips anything already listed. Stop and restart any time. If a node crashes mid-item, that item is retried automatically on the next run.

**Vision input.** Images are encoded as base64 data URLs and sent to a vision-capable model. Input type is detected from the file extension.

**Standard library plus `requests`.** No async runtime, no database, no message broker.

```
dataset/
  img001.png  img002.png  ...  img999.png
        |
        v
┌─────────────────────────────────────┐
│         Shared queue.Queue          │
└──────────────┬──────────────────────┘
               |
      ┌────────┴────────┐
      v                 v
┌──────────┐      ┌──────────┐
│ Worker A │      │ Worker B │
│ node_a   │      │ node_b   │
└────┬─────┘      └────┬─────┘
     |                 |
     └────────┬─────────┘
              v
   img001.txt  written next to  img001.png
   img002.txt  written next to  img002.png
              |
              v
        output/
          use/
            img001.json     (full metadata, kept for reference)
            img002.json
          review/
            img003.json     (flagged -- no .txt written)
          completed.txt
          failed.txt
          run_log.txt
```

## If you want JSON

The captioning example writes `.txt` files. If you're using this for something else, leave `post_process` as `pass` in `batch_runner.py` and the runner writes structured JSON output to the `output/` directory instead. The setup is the same: copy the `STAGE*_SYSTEM` strings and `classify_output` from whichever example fits your task into `batch_runner.py` and run.

## Other things this is good at

**`image_tagging.py`** Tags a folder of images with structured metadata — category, dominant colors, keywords, scene type, mood. Stage 1 describes the image, Stage 2 extracts the fields, Stage 3 checks for internal consistency (outdoor scenes shouldn't have fluorescent lighting, etc.). Output is sorted by category subfolder.

**`invoice_parsing.py`** Processes (OCR) invoices and receipts into structured line items with vendor name, individual amounts, subtotal, tax, and total. Stage 3 checks the arithmetic. If subtotal + tax doesn't equal the stated total, it flags the discrepancy rather than silently passing bad data through.

**`meeting_notes.py`** Takes raw meeting transcripts and extracts structured action items: owner, task description, and due date. Stage 1 reads the transcript and identifies what was decided and assigned. Stage 2 pulls those into a consistent schema. Stage 3 checks that every action item has a clear owner and that due dates are in a usable format.

**`technical_documentation.py`** Indexes API references, guides, changelogs, and similar docs into a searchable metadata format: title, document type, summary, covered endpoints or features, and keyword tags. Useful for building a local search index over a large documentation set. This can also be great for RAG (LLMs love markdown) of your own personal appliance manuals, etc. I once converted my furnace manual to markdown and I was able to use LLMs to help me diagnose my furnace :D

**`bulk_translation.py`** Translates foreign-language documents to English and extracts structured metadata alongside the translation: detected source language, domain, topic tags, and a confidence note if the source text was ambiguous or mixed-language. Stage 3 checks that the translation reads naturally and flags anything that looks like a literal or machine-style rendering. Works surprisingly well with Thai :)

**`job_posting_normalization.py`** Normalizes scraped job postings into a consistent schema regardless of how the original was formatted: title, seniority level, required and preferred skills, salary range, remote policy, and location. Stage 3 checks for conflicting signals (a "junior" title with 8+ years required, fully remote listed with a mandatory office location, etc.).

**`audio_transcript_cleanup.py`** Takes raw Whisper output which is know for run-on sentences, no punctuation, no speaker labels, etc. and produces a clean, readable transcript with proper punctuation and speaker attribution. Stage 2 also extracts any action items mentioned in the conversation as a separate structured list. 

## Stopping and resuming

Three ways to stop a run:

- **Ctrl+C.** Workers finish their current item and exit cleanly. Ctrl+C again hard-kills immediately.
- **STOP file.** Drop a file named `STOP` in the working directory. Same effect as Ctrl+C. Useful when you don't have an attached terminal.
- **Hard kill.** The runner prints its PID at startup. `taskkill /PID 12345 /F` or `kill -9 12345`. Anything in flight gets retried on the next run.

`python batch_runner.py` again skips anything already in `completed.txt` or `failed.txt` and processes the rest.

`python batch_runner.py --node 0` runs only the first node. Useful for testing prompts against one endpoint before turning the full batch loose.

## Caveats

**In-flight items on hard kill.** A worker killed mid-pipeline never writes to `completed.txt`, so the item is retried from Stage 1 on the next run. Any `.txt` already written gets overwritten — the content should be identical.

**No startup health checks.** If a node is unreachable, its worker fails fast and logs the error. Other workers carry on with the full queue. Failed items go in `failed.txt` and retry next run.

**No rate limiting.** Requests fire as fast as the model answers. Local inference rarely needs throttling, but if yours does, add `time.sleep()` in the worker.

**Sequential within an item.** Stage 1 has to finish before Stage 2 starts, and Stage 2 before Stage 3. Parallelism is across items, not within a single item's pipeline.

## Requirements

- Python 3.9+
- `requests`
- One or more machines running LM Studio, Ollama, or any OpenAI-compatible inference server
- A vision-capable model for image inputs (`llava`, `qwen-vl`, `minicpm-v`)

The machine running `batch_runner.py` doesn't need a GPU. It only coordinates.

## License

MIT - it's a weekend project, do whatever you want.
-Dave
