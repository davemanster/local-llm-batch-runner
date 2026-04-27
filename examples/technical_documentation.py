"""
Example: technical documentation indexing

Drop these prompts into batch_runner.py to build a searchable metadata index
from a folder of technical documents: API references, user guides, changelogs,
spec sheets, READMEs, and similar content. Input files should be plain text
or markdown.
"""

STAGE1_SYSTEM = """
You are reading a technical document. Examine it carefully and write a thorough
prose description of its contents:

- What product, system, library, or tool this document covers
- The document type: is it a reference, a guide, a tutorial, a changelog, a spec,
  a README, or something else?
- Who the intended audience appears to be (developers, end users, administrators, etc.)
- What version, release, or edition this document applies to, if mentioned
- The major topics, sections, or features documented
- Any prerequisites or dependencies mentioned
- Key technical terms, concepts, or identifiers that are central to the content
- The overall scope: does it cover an entire system or one specific area?

Write as detailed prose. Do not produce JSON or lists.
""".strip()


STAGE2_SYSTEM = """
You are converting a prose description of a technical document into structured metadata.

Given the description in the user message, produce a JSON object with these fields:

{
  "title": "string -- the document title or an inferred descriptive title",
  "doc_type": "reference | guide | tutorial | changelog | spec | readme | other",
  "product": "string or null -- the product, library, or system being documented",
  "version": "string or null -- version or release this document applies to",
  "audience": "string -- intended audience (e.g. 'developers', 'end users', 'sysadmins')",
  "topics": ["array of 3-10 topic or feature strings the document covers"],
  "prerequisites": ["array of prerequisite strings, or empty array if none"],
  "key_terms": ["array of 3-10 important technical terms or identifiers"],
  "summary": "string -- 2-3 sentences describing what this document covers and who it is for",
  "scope": "full-reference | partial | overview | unknown"
}

Use null for fields not determinable from the document.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this technical documentation metadata JSON for consistency and completeness.

Checks to perform:
- doc_type must be one of: reference, guide, tutorial, changelog, spec, readme, other.
  If the value does not match, correct it to the closest valid option.
- topics must have at least 3 entries. If fewer, expand based on summary and key_terms.
- key_terms must have at least 3 entries. If fewer, infer from topics and product name.
- summary must be 2-3 complete sentences. If it is one sentence or a fragment,
  expand it using available fields (product, doc_type, audience, topics).
- If audience is very generic (e.g. just "users"), refine it based on doc_type.
  A "reference" is typically for developers; a "guide" may be broader.
- scope should be "full-reference" only if the document covers an entire system or API.
  If it covers one feature or module, use "partial". Correct if inconsistent.

Fix anything that fails. Return the corrected JSON.
Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by document type."""
    return parsed.get("doc_type", "other").lower().replace(" ", "_")
