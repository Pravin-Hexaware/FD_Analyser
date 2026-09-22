# Prompts index

All LLM / agent prompts live here as `.md` files. Edit these files to change
behavior — Python loads them via `from prompts.loader import load_prompt`.

Edits are picked up on the next LLM call (no code change needed). Restart the
server if a module cached a prompt string at import time (e.g. `portal_flow`).

## Orchestration / heal agent

| File | Purpose |
|------|---------|
| `orchestration_portal_canonical_flow.md` | Canonical BSE Fetch Filings flow |
| `orchestration_heal_goal.md` | Heal goal template (`{test_input}`) |
| `analysis_initial_prompt.md` | First analysis of broken portal module |
| `analysis_final_prompt.md` | ChangePlan from DOM + analysis |
| `coding_system_prompt.md` | Coding agent system message |
| `coding_interaction_guards.md` | Mandatory portal interaction rules |
| `coding_prompt.md` | First-pass codegen user prompt |
| `coding_regeneration_prompt.md` | Regen after harness failure |
| `dom_combined_prompt.md` | DOM filter + understand agent |

## Chatbot / financial analysis

| File | Purpose |
|------|---------|
| `chatbot_financial_report_system.md` | Full institutional report system prompt |
| `chatbot_financial_report_multi_first.md` | Multi-LLM first-pass body |
| `chatbot_financial_analyst_simple.md` | Compact metrics-table analysis |
| `chatbot_financial_analyst_qa.md` | Manager-style Q&A over JSON |
| `chatbot_financial_analyst_concise.md` | Short answer over financial data |
| `chatbot_news_impact_system.md` | Append news-driven assessment section |
| `chatbot_news_context_system.md` | Short strategic news insights (optional) |
| `news_agent_system.md` | News fetch/filter agent |

Placeholders use Python `{name}` syntax. Literal braces in JSON examples must
be written as `{{` and `}}`.
