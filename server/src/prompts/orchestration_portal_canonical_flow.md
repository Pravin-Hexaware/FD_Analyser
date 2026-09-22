CANONICAL BSE FINANCIAL RESULTS FLOW (comp_resultsnew):

1. NAVIGATE to https://www.bseindia.com/corporates/comp_resultsnew
2. SEARCH (fill_search):
   - Locate the Security Name / scrip search input in the Financial Results form
     (container-scoped: div.get-input-section ... #scripsearchtxtbx).
   - Type the 4–6 digit BSE scrip code character-by-character (delay ~80–150ms).
   - Wait/poll for autocomplete list (#SearchQuotediv2 #ulSearchQuote2 li — outside form container).
   - MUST click the FIRST real suggestion before any filters/submit (skip "No Match Found").
   - NEVER skip the autocomplete click — typing alone leaves search unbound → EMPTY grid.
   - NEVER click "No Match Found" as a selectable item.
   - fill_search(page, company, expected_scrip=None) MUST accept expected_scrip from CSV.
   - If scrip suggestions fail: type company symbol from API, then click first LI (or ArrowDown+Enter).
   - Do NOT use inject_hidden_scrip as a soft-pass; empty grid after Submit means click was missing.

3. FILTERS (apply_filters):
   - Optional Segment dropdown → "Equity" when present (container-scoped; not period dropdown).
   - Result Period → "ALL"
   - Industry → "ALL"
   - Broadcast Period → "Beyond last 1 year" (dropdown value "7" / 7th option — NOT "Last 1 year").

4. SUBMIT: click Submit, wait 0–5 seconds for #ContentPlaceHolder1_gvData to refresh.

5. GRID: parse table rows — Security Code, Security Name, Industry, Period, Std XBRL link, Con XBRL link.
   - Fetch Filings collects Std XBRL column only.
   - Filter periods: quarterly reports only (period token 2nd char 'Q' e.g. DQ/SQ/MQ/JQ).
   - Filter periods: within past 5 fiscal years.

6. SITE HEALTH (before any heal agent):
   - Reload https://www.bseindia.com/corporates/comp_resultsnew (fresh navigation + reload).
   - Inspect the DEFAULT landing results table (#ContentPlaceHolder1_gvData) with NO company search applied.
   - If the default table has ZERO meaningful records (or shows "No Records Found"): treat as BSE
     downtime / outage — DO NOT start the heal/coding agent; tell the user the website is facing
     an issue and to try again after some time.
   - If the default table HAS records: site is up; heal agent may run for real UI drift only.

7. HEAL: raise PlaywrightHealRequired only when a contract control is missing/changed
   (search input, suggestions, filters, submit, grid) — NOT when autocomplete is slow,
   and NOT when the default landing grid is empty (that is downtime, not UI drift).
