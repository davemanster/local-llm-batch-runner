"""
Example: bulk document translation

Drop these prompts into batch_runner.py to translate a folder of foreign-language
documents into English with structured metadata. Works with plain text files
containing documents, articles, reports, manuals, or similar content.
"""

STAGE1_SYSTEM = """
You are translating a document from its original language into English.

Translate the full document completely and accurately:

- Preserve the meaning and tone of the original
- Keep technical terms, proper nouns, brand names, and model numbers exactly
  as they appear in the original (do not translate them unless a standard
  English equivalent is universally understood)
- Preserve the document's structure: headings, numbered lists, section breaks
- Where a phrase is ambiguous or idiomatic, provide the translation you believe
  is most accurate and note the original phrase in parentheses
- After the translation, include a short section labeled TRANSLATOR NOTES listing
  any terms or phrases you were uncertain about, or where the source was unclear

Translate everything. Do not summarize, skip sections, or paraphrase.
""".strip()


STAGE2_SYSTEM = """
You are converting a translated document and its translator notes into structured metadata.

Given the translated text in the user message, produce a JSON object with these fields:

{
  "original_language": "string -- the detected original language (e.g. 'French', 'Japanese')",
  "doc_type": "manual | report | article | contract | correspondence | specification | other",
  "word_count_estimate": "integer -- approximate word count of the translated text",
  "subject": "string -- the main subject or topic of the document in one phrase",
  "summary": "string -- 2-3 sentences summarizing the document content",
  "key_terms": [
    {
      "original": "string -- the term in the original language",
      "translated": "string -- the English translation used"
    }
  ],
  "uncertain_terms": ["array of strings -- terms flagged in TRANSLATOR NOTES as uncertain"],
  "needs_review": false
}

Populate key_terms from any preserved original-language terms in the translation.
Populate uncertain_terms from the TRANSLATOR NOTES section if present.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this translation metadata JSON for completeness and consistency.

Checks to perform:
- original_language must be a full language name (e.g. "French", not "fr" or "unknown").
  If it is a language code, expand it to the full language name.
- doc_type must be one of: manual, report, article, contract, correspondence,
  specification, other. Correct if it does not match.
- If uncertain_terms is non-empty, set needs_review to true.
- Each entry in key_terms must have both "original" and "translated" fields populated.
  Remove any entry where either field is empty or null.
- summary must be 2-3 complete sentences. If shorter, expand using subject and doc_type.
- word_count_estimate should be a reasonable positive integer. If it is 0 or null,
  set it to null rather than guessing.

Fix anything that fails. Return the corrected JSON.
Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by original language."""
    lang = parsed.get("original_language", "unknown")
    return lang.lower().replace(" ", "_")
