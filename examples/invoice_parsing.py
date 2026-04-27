"""
Example: invoice and receipt parsing

Drop these prompts into batch_runner.py to extract structured data from
scanned invoices, receipts, or purchase orders. Works with text files
(OCR output) or directly with image files if using a vision model.
"""

STAGE1_SYSTEM = """
You are a careful document analyst specializing in financial documents.

Read this document thoroughly and describe everything you can see:

- The vendor or business name, address, contact information
- The document type (invoice, receipt, purchase order, statement, etc.)
- All dates visible (invoice date, due date, payment date, etc.)
- Every line item: description, quantity, unit price
- All totals, subtotals, taxes, fees, and discounts
- Payment terms, invoice number, order number, or reference codes
- Any notes, terms, or special conditions

Transcribe numbers exactly as they appear. If a value is unclear or illegible,
say so explicitly -- do not guess. Write as thorough prose.
""".strip()


STAGE2_SYSTEM = """
You are converting a prose document description into structured data.

Given the description in the user message, produce a JSON object with these fields:

{
  "document_type": "invoice | receipt | purchase_order | statement | other",
  "vendor": {
    "name": "string",
    "address": "string or null",
    "phone": "string or null",
    "email": "string or null"
  },
  "document_number": "string or null -- invoice/receipt/PO number",
  "date_issued": "YYYY-MM-DD or null",
  "date_due": "YYYY-MM-DD or null",
  "line_items": [
    {
      "description": "string",
      "quantity": number or null,
      "unit_price": number or null,
      "total": number or null
    }
  ],
  "subtotal": number or null,
  "tax": number or null,
  "tax_rate_pct": number or null,
  "discounts": number or null,
  "total": number,
  "currency": "USD or detected currency code",
  "payment_terms": "string or null",
  "notes": "string or null",
  "needs_review": false
}

Use null for any field not present in the document.
Output ONLY valid JSON. No prose, no code fences. Start with { and end with }.
""".strip()


STAGE3_SYSTEM = """
Review this invoice/receipt JSON for arithmetic consistency and completeness.

Checks to perform:
1. If line_items are present and have quantity + unit_price, verify each item's total
   equals quantity * unit_price (within rounding). Flag mismatches.
2. If subtotal and line_items are both present, verify subtotal ≈ sum of line item totals.
   Flag if they differ by more than 0.02.
3. If subtotal, tax, and total are all present, verify subtotal + tax ≈ total.
   Flag if they differ by more than 0.02.
4. If total is null or missing, calculate it from available fields if possible.
5. If any date fields appear to be in a non-ISO format (e.g. "01/15/2024"),
   convert them to YYYY-MM-DD.

If any arithmetic check fails, set "needs_review": true and add a
"review_notes" field listing each specific discrepancy.

If everything checks out, return the JSON unchanged (needs_review stays false).

Output ONLY valid JSON. No prose. Start with { and end with }.
""".strip()


def classify_output(parsed: dict) -> str:
    """Organize output by document type."""
    return parsed.get("document_type", "other").lower().replace(" ", "_")
