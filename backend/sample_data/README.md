# AI Test Data Generator

This script generates synthetic PSR and CAMT files specifically designed to exercise the Pass 2 AI Triage engine. 

The deterministic rules (P1-P4) will catch the first 50 records (if configured as such). The remaining 300+ records are engineered to fail all deterministic rules and fall through to the AI engine (`POST /api/reconcile/ai-triage`), creating a massive pool of suggestions for testing and demonstration purposes.

## How to use

1.  Navigate to the sample data folder:
    ```bash
    cd backend/sample_data
    ```

2.  Run the generation script:
    ```bash
    python generate_ai_samples.py
    ```

3.  The script will generate new files each time, formatted as:
    -   `PSR-350-<RANDOM>.txt` (350+ records)
    -   `CAMT-400-<RANDOM>.xml` (400+ entries)

4.  Upload these files in the **Data Intake** screen of the application.
5.  Click **Reconcile** → The auto-match rate will drop, leaving hundreds of exceptions.
6.  Click **Run AI Triage** → The UI will populate with hundreds of "AI-Assisted Suggested Match" and "AI - Analyst Adjudication Required" cases.

## Included Scenarios

The script programmatically generates varying scenarios to trigger different zones of the embedding logic (Cosine similarities):

-   **Scenario 0 (1-50):** Deterministic matches (exact EndToEndId and PMT-REF).
-   **Scenario A (51-120):** AI *Clear zone*. PSR name appears verbatim in CAMT remittance, but the main counterparty names differ enough to fail P4 fuzzy matching.
-   **Scenario B (121-190):** AI *Clear zone*. PSR invoice alias appears in CAMT remittance.
-   **Scenario C (191-260):** AI *Maybe zone*. Semantic keyword overlap only (e.g., "hauling" vs "road transport"). Fails thresholds but goes to LLM adjudication (Tier 2c).
-   **Scenario D (261-310):** AI *Maybe zone* + minor amount deltas. Semantic overlap with amounts differing by ≤50 (tests the pre-filter tolerance).
-   **Scenario E (311-350):** AI *Clear zone* + 1-day date offset (tests `in_transit_days` window tolerance).
-   **Orphans (351-400):** Bank-only items injected into CAMT with no corresponding PSR, serving as noise to test embedding precision.