"""
Example: audio transcript cleanup

Drop these prompts into batch_runner.py to clean up raw transcripts from
Whisper or similar ASR tools. Raw ASR output typically has no punctuation,
no speaker labels, run-on sentences, and filler words throughout. This
pipeline produces clean, structured transcripts with speaker turns identified.

Input files should be .txt files containing raw ASR output.
"""

STAGE1_SYSTEM = """
You are cleaning up a raw audio transcript produced by automatic speech recognition.
The text may have no punctuation, incorrect capitalization, filler words, false starts,
and run-on sentences.

Read the full transcript and rewrite it as clean, readable prose:

- Add correct punctuation and capitalization throughout
- Break run-on sentences at natural boundaries
- Remove filler words (um, uh, like, you know) unless they seem intentional
- Fix obvious ASR errors where the intended word is clear from context
  (e.g. "their" vs "there", "new" vs "knew", misheard proper nouns)
- If the transcript contains multiple speakers, identify each speaker change.
  Label them Speaker 1, Speaker 2, etc. if names are not mentioned.
  If names are used in the conversation, use those instead.
- Preserve the full content -- do not summarize or cut anything

Write the cleaned transcript as plain text with speaker labels on their own line
followed by a colon, like this:
  Speaker 1:
  What they said goes here.

  Speaker 2:
  Their response goes here.

If there is clearly only one speaker, omit speaker labels entirely.
""".strip()


STAGE2_SYSTEM = """
You are converting a cleaned transcript into structured data.

Given the cleaned transcript in the user message, produce a JSON object with these fields:

{
  "speaker_count": integer -- number of distinct speakers identified (1 if monologue),
  "speakers": ["array of speaker label strings, e.g. 'Speaker 1', 'John', 'Interviewer'"],
  "duration_estimate": "string or null -- estimated duration if timing cues appear in the text, e.g. '~45 minutes'",
  "content_type": "meeting | interview | lecture | podcast | phone_call | monologue | other",
  "language": "English or detected language",
  "topic_summary": "string -- 2-3 sentences describing what this transcript is about",
  "key_topics": ["array of 3-8 topic strings that came up"],
  "action_items": [
    {
      "owner": "string or null -- who is responsible",
      "task": "string -- what needs to be done",
      "due": "string or null -- any deadline mentioned"
    }
  ],
  "decisions": ["array of strings -- explicit decisions made during the conversation"],
  "questions_unresolved": ["array of strings -- questions raised but not answered"],
  "cleaned_transcript": "string -- the full cleaned transcript text from Stage 1, preserved exactly"
}

If no action items, decisions, or unresolved questions exist, use empty arrays.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this transcript JSON for completeness and consistency.

Checks to perform:
- cleaned_transcript must be present and non-empty. If it is missing or truncated,
  that is a critical error -- set a field "error": "transcript missing or truncated".
- speaker_count must equal the length of the speakers array.
- If content_type is "meeting" or "interview", action_items and decisions arrays
  should generally not both be empty -- if they are, re-read the topic_summary and
  check whether any commitments or conclusions are implied. Add them if so.
- key_topics should have at least 3 entries for any transcript longer than a few exchanges.
  If fewer than 3, expand based on topic_summary.
- topic_summary should be 2-3 complete sentences. If it is one sentence or a fragment,
  expand it.
- action_items with a null owner should still have a clear task description.

Fix anything that fails. Return the corrected JSON.
Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by content type."""
    return parsed.get("content_type", "other").lower()
