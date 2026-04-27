"""
Example: bulk image tagging

Drop these prompts into batch_runner.py to tag a folder of images with
structured metadata. Requires a vision-capable model (llava, qwen-vl,
minicpm-v, etc.).
"""

STAGE1_SYSTEM = """
You are a detailed image analyst. Examine this image carefully and write a thorough
prose description of everything you observe:

- All visible objects, their positions, and relationships
- Colors, textures, lighting, and composition
- Any text or symbols visible in the image
- The setting or environment
- The overall mood or atmosphere
- Any notable details that would help someone understand the image without seeing it

Be specific and comprehensive. Do NOT produce JSON or lists. Write flowing prose.
""".strip()


STAGE2_SYSTEM = """
You are converting a prose image description into structured metadata.

Given the description in the user message, produce a JSON object with exactly these fields:

{
  "category": "string -- the primary subject category (e.g. 'nature', 'architecture', 'portrait', 'product', 'food', 'event')",
  "subcategory": "string -- a more specific category within the primary",
  "dominant_colors": ["array of 2-4 color strings"],
  "contains_text": true or false,
  "subject_count": integer -- number of primary subjects (0 if abstract/landscape),
  "scene_type": "indoor or outdoor or studio or abstract",
  "keywords": ["array of 5-10 descriptive keywords useful for search"],
  "mood": "string -- the overall mood or tone (e.g. 'serene', 'dynamic', 'melancholic', 'joyful')",
  "description_one_line": "string -- a single sentence summarizing the image for alt-text"
}

Output ONLY valid JSON. No prose, no code fences, no explanation.
Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this JSON metadata object for consistency and completeness.

Checks to perform:
- All required fields are present and non-empty
- dominant_colors contains 2-4 entries (trim or expand if needed)
- keywords contains 5-10 entries
- subject_count is 0 only for abstract or pure landscape images
- scene_type matches what the description implies
- description_one_line is a complete sentence under 150 characters
- category and subcategory are consistent with each other

If everything is consistent, return the JSON unchanged.
If anything needs correction, fix it and return the corrected JSON.

Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by primary category."""
    return parsed.get("category", "uncategorized").lower().replace(" ", "_")
