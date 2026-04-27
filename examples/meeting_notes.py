"""
Example: meeting notes to action items

Drop these prompts into batch_runner.py to process a folder of raw meeting
notes or transcripts and extract structured action items and decisions.
Input files should be plain text (.txt or .md).
"""

STAGE1_SYSTEM = """
You are reading raw meeting notes or a meeting transcript.

Read them carefully and write a thorough plain-English summary of everything covered:

- Who attended, if mentioned
- What was discussed: every topic, not just the major ones
- What was decided: explicit decisions made during the meeting
- What was assigned: tasks, owners, and any deadlines mentioned
- Any open questions or items flagged for follow-up
- The general outcome of the meeting

Be thorough. Do not skip items because they seem minor.
Write as flowing prose. Do not produce JSON or bullet lists.
""".strip()


STAGE2_SYSTEM = """
You are converting a meeting summary into structured data.

Given the summary in the user message, produce a JSON object with these fields:

{
  "meeting_title": "string or null -- inferred title or topic of the meeting",
  "date": "YYYY-MM-DD or null -- if a date was mentioned",
  "attendees": ["array of name strings -- or empty array if not mentioned"],
  "topics_discussed": ["array of strings -- every distinct topic covered"],
  "decisions": ["array of strings -- explicit decisions made"],
  "action_items": [
    {
      "owner": "string or null -- who is responsible",
      "task": "string -- what needs to be done",
      "due_date": "string or null -- any deadline mentioned",
      "priority": "high | medium | low | unknown"
    }
  ],
  "open_questions": ["array of strings -- questions raised but not resolved"],
  "next_meeting": "string or null -- date or conditions for the next meeting if mentioned",
  "summary_one_line": "string -- a single sentence describing what this meeting was about"
}

Use null for any field not determinable from the notes.
Use empty arrays for decisions, action_items, open_questions if none exist.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this meeting JSON for completeness and consistency.

Checks to perform:
- Every action_item must have a non-empty task string. Owner can be null, task cannot.
- If any action_item has priority "unknown" and the task description implies urgency
  (words like "urgent", "ASAP", "critical", "blocker"), upgrade priority to "high".
- decisions and action_items should not overlap. A decision is something already
  resolved; an action item is something still to be done. If an action item is
  phrased as a past decision, move it to decisions and remove it from action_items.
- open_questions should be phrased as questions (ending with ?). Reformat if needed.
- summary_one_line must be a single complete sentence under 160 characters.

Fix anything that fails. Return the corrected JSON.
Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by month if date is present, otherwise 'undated'."""
    date = parsed.get("date")
    if date and len(date) >= 7:
        return date[:7]  # YYYY-MM
    return "undated"
