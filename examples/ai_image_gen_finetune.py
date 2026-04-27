"""
Example: caption a dataset for AI image-gen fine-tuning

Drop everything in this file into batch_runner.py to caption a folder of
images for training a diffusion model (Flux, SDXL, SD3, etc.) or a LoRA.
Requires a vision-capable model.

Set TRIGGER_WORD to whatever unique token you want every caption to start
with. Set it to "" for a general fine-tune with no trigger.

When each image finishes, post_process() writes a .txt caption file next to
the source image -- the format kohya_ss, ai-toolkit, and diffusion-pipe
expect:

    dataset/
      img001.png
      img001.txt   <-- written automatically
      img002.png
      img002.txt

Images flagged as low quality or watermarked get skip_recommended=True and
are sorted into output/review/ instead of output/use/. Their .txt files are
not written -- review them manually before deciding whether to include them.
"""

from pathlib import Path

TRIGGER_WORD = "mysubject"  # leave empty string for no trigger


STAGE1_SYSTEM = """
You are looking at a single training image for a diffusion model fine-tune.

Describe what is actually in the frame, in plain natural language, the way
someone would describe it to a friend who can't see it. Cover:

- The main subject and what it's doing
- Pose, expression, gaze direction if it's a person or animal
- Clothing, materials, colors, distinctive details
- The setting or background and what's in it
- Lighting style (soft, harsh, golden hour, studio, overcast, etc.)
- Camera framing (close-up, wide shot, low angle, overhead, etc.)
- Image style or medium (photo, oil painting, 3D render, anime, sketch)
- Any text, logos, watermarks, or signatures visible

Do not invent details that aren't in the image. If you can't tell what
something is, say so or skip it. Do not editorialize about mood or symbolism.

Write as flowing prose, not a list. Aim for 80 to 200 words.
""".strip()


STAGE2_SYSTEM = f"""
You are turning a long image description into a training caption for a
diffusion model fine-tune.

Given the description in the user message, produce a JSON object with these fields:

{{
  "caption": "string -- the final training caption, see rules below",
  "trigger_word": "{TRIGGER_WORD}",
  "subject": "string -- the primary subject in 1 to 4 words (e.g. 'a woman', 'a red sports car', 'a wooden chair')",
  "style": "string -- 'photo', 'illustration', 'anime', 'oil painting', '3d render', 'sketch', or other short style descriptor",
  "shot_type": "close-up | medium | wide | full-body | overhead | low-angle | unknown",
  "lighting": "string -- short description of lighting (e.g. 'soft natural', 'harsh studio', 'golden hour')",
  "has_text": true or false,
  "has_watermark": true or false,
  "quality_flags": ["array of any of: 'blurry', 'low_resolution', 'cropped_subject', 'text_visible', 'watermark', 'multiple_subjects', 'cluttered_background'"]
}}

Caption rules:
- 1 to 3 sentences, natural language, no booru-style tag lists
- Start with the trigger_word followed by a comma if trigger_word is non-empty
- After the trigger, describe the subject, then the action or pose, then setting and lighting
- Keep concrete visual facts. Drop anything subjective ("beautiful", "dreamy", "majestic")
- Do not mention the photographer, the model, the camera brand, or copyright text
- Do not include watermarks or logos in the caption text even if visible

Output ONLY valid JSON. No prose, no code fences. Start with {{ and end with }}.
""".strip()


STAGE3_SYSTEM = f"""
Review this training caption JSON for fitness as fine-tuning data.

Checks to perform:
- If trigger_word is "{TRIGGER_WORD}" and "{TRIGGER_WORD}" is non-empty,
  the caption MUST start with that exact trigger followed by a comma.
  If it doesn't, prepend it.
- caption must be between 20 and 350 characters. If longer, tighten it.
  If shorter, expand using subject, style, lighting, shot_type.
- caption must not contain: "image of", "picture of", "photograph of", "AI",
  "generated", "rendered by", "created by". Strip these phrases.
- If has_watermark is true or quality_flags contains "watermark", add
  "skip_recommended": true and a "skip_reason" field explaining why.
- If quality_flags contains "blurry" or "low_resolution", also add
  "skip_recommended": true with the reason.
- Otherwise set "skip_recommended": false.

Fix the caption in place. Return the corrected JSON.
Output ONLY valid JSON. No prose. Start with {{ and end with }}.
""".strip()


def classify_output(parsed: dict) -> str:
    """Sort into 'use' or 'review' so you can quickly cull bad captions."""
    if parsed.get("skip_recommended"):
        return "review"
    return "use"


def post_process(parsed: dict, output_stem: Path, source_path: Path):
    """Write the caption as a .txt file next to the source image."""
    if parsed.get("skip_recommended"):
        return
    caption = parsed.get("caption", "").strip()
    if caption:
        source_path.with_suffix(".txt").write_text(caption, encoding="utf-8")
