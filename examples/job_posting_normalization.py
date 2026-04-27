"""
Example: job posting normalization

Drop these prompts into batch_runner.py to normalize a folder of job postings
into consistent structured data. Works with raw text files, HTML dumps, or
scraped content. Useful for building job boards, doing compensation research,
or tracking hiring trends across companies.
"""

STAGE1_SYSTEM = """
You are reading a job posting. Extract and describe everything in it thoroughly:

- The job title exactly as written, and what seniority level it implies
- The company name and any details about the company mentioned
- The location, and whether remote, hybrid, or on-site work is specified
- Every required skill, technology, tool, language, or qualification mentioned
- Every preferred or nice-to-have skill mentioned (distinguish these from required)
- Years of experience requested, if any
- Education requirements, if any
- Salary, compensation, or pay range if mentioned -- exact figures
- Benefits mentioned (equity, health, PTO, etc.)
- The team or department this role sits in
- What the role actually does day-to-day based on the responsibilities section
- Any unusual requirements, conditions, or red flags

Be thorough. Preserve exact wording for skills and titles -- do not paraphrase
or normalize them yet. Write as detailed prose.
""".strip()


STAGE2_SYSTEM = """
You are converting a prose job posting description into structured data.

Given the description in the user message, produce a JSON object with these fields:

{
  "title_raw": "string -- the job title exactly as written in the posting",
  "title_normalized": "string -- cleaned, canonical title (e.g. 'Senior Software Engineer')",
  "seniority": "intern | junior | mid | senior | staff | principal | lead | manager | director | vp | executive | unknown",
  "company": "string or null",
  "location": "string or null -- city/region as written",
  "remote_policy": "remote | hybrid | onsite | unknown",
  "employment_type": "full-time | part-time | contract | freelance | unknown",
  "required_skills": ["array of strings -- exact skill/tool/language names"],
  "preferred_skills": ["array of strings -- nice-to-haves only"],
  "years_experience_min": number or null,
  "years_experience_max": number or null,
  "education_required": "string or null -- e.g. 'Bachelor's in Computer Science' or 'not specified'",
  "salary_min": number or null,
  "salary_max": number or null,
  "salary_currency": "USD or detected currency code or null",
  "salary_period": "annual | hourly | monthly | null",
  "equity": true or false,
  "benefits": ["array of benefit strings mentioned"],
  "department": "string or null -- team or department name",
  "summary": "string -- one sentence describing what this role actually does"
}

Use null for any field not present in the posting.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this job posting JSON for consistency and completeness.

Checks to perform:
- seniority must be consistent with title_normalized and years_experience_min.
  A "Junior" title with 8+ years required is a conflict -- flag it.
- If years_experience_min > years_experience_max (and both are non-null), swap them.
- required_skills and preferred_skills should not overlap -- move any duplicates
  to required_skills only.
- If salary_min > salary_max (and both are non-null), swap them.
- salary_period should be "annual" if the figures are in the tens of thousands,
  "hourly" if they are under 200. Correct it if it looks wrong.
- remote_policy should be "remote" only if the posting explicitly says remote or
  fully remote. "Hybrid" if it specifies days in office. "Onsite" if no remote
  option is mentioned. Correct if inconsistent with the summary.
- summary should be a single complete sentence under 160 characters. Trim if needed.

If any check fails, fix it in place. If everything looks consistent, return unchanged.
Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by seniority level."""
    return parsed.get("seniority", "unknown").lower()
