# Hong Kong History Research Project - Instructions

## Model Strategy
To optimize for performance and quota:
1. **Development/Coding Agent:** Use Pro-class models (e.g., `gemini-pro`) for complex reasoning, refactoring, and debugging.
2. **Research Pipeline (Cron):** Use Flash-class models (e.g., `gemini-3.5-flash`) for high-throughput automated tasks like summarization and categorization.

## Automation & Pipeline Configuration
- **Frequency:** The pipeline runs every 3 hours via GitHub Actions. Each run classifies new RSS items, then spends leftover quota drafting history pages (`scripts/seed_history.py`).
- **Quota:** Per-model limits live in `scripts/models.json`; `scripts/gemini_pool.py` enforces them and falls through the models in order.
- **Error Handling:** The pipeline implements exponential backoff and structured JSON outputs for reliable data ingestion.
- **Git Strategy:** Automated commits and pushes to `origin/main` happen locally and are pushed automatically.
