# Data-Ingestion Feasibility Report

## Executive Summary
Use Steam for the initial automated technical prototype because direct structured access and pagination were successfully demonstrated. Amazon browser-response parsing is also technically feasible and commercially broader, but unattended direct access remains unresolved. Continue Amazon only through a controlled browser-based or otherwise approved access proof of concept before selecting it for automated production ingestion.

## Project Objective
Assess whether Amazon Product Reviews or Steam User Reviews is a better limited-test source for future review ingestion and sentiment-analysis work.

## Scope and Test Method
This is a small feasibility assessment. It does not build a production scraper, database, scheduler, or sentiment model.

## Evaluation Criteria
Accessibility, review volume, available metadata, data quality, commercial value, and long-term maintainability.

## Steam Findings
- Live request executed: yes
- Offline saved-response parsing executed: no
- Saved response batches parsed: 0
- Live requests attempted: 18
- HTTP status codes: 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200
- Request batches attempted: 18
- Reviews collected: 150
- Duplicates within final normalized dataset: 0
- Repeat-run overlap: 150
- Repeat-run overlap rate: 100%
- Blocking status: no
- CAPTCHA status: no
- Pagination demonstrated: yes
- Parser errors: 0
- Warnings: none
- Rating: not applicable; Steam provides a binary recommendation label.

## Amazon Findings
- Live request executed: no
- Offline saved-response parsing executed: yes
- Saved response batches parsed: 3
- Live requests attempted: 0
- HTTP status codes: none
- Request batches attempted: 0
- Reviews collected: 30
- Duplicates within final normalized dataset: 0
- Repeat-run overlap: not applicable
- Repeat-run overlap rate: not applicable
- Blocking status: not assessed
- CAPTCHA status: not assessed
- Pagination demonstrated: yes
- Parser errors: 0
- Warnings: none
- Direct live accessibility: not tested in this run.
- Browser-captured offline parseability: successfully demonstrated.
- Browser-captured pagination: successfully demonstrated.

## Data-Quality Comparison
- steam: rows=150, duplicates within final dataset=0, repeat-run overlap=150, empty text=1, parser errors=0
- steam field note: Rating: not applicable; Steam provides a binary recommendation label.
- steam not-applicable fields: rating, review_title, verified_purchase
- amazon: rows=30, duplicates within final dataset=0, repeat-run overlap=not applicable, empty text=0, parser errors=0
- amazon not-applicable fields: recommendation, funny_votes, playtime_forever, playtime_at_review

## Accessibility and Pagination Comparison
- Amazon evidence: Direct live accessibility was not tested in this run. Offline parsing succeeded for 3 browser-captured response batches containing 30 unique reviews, and sequential pagination was demonstrated.
- Steam evidence: 18 requests, success rate 1.0, blocked=False, pagination=True
- Amazon assessment: Offline parseability and browser-captured pagination demonstrated; direct automated accessibility unresolved.
- Steam assessment: Strong in this limited test.
- Confidence: limited

## Commercial Relevance
Amazon is closely aligned with broad product reviews and customer-product insight. Steam provides rich user feedback but is gaming-specific.

## Maintainability Risks
Steam uses a structured public JSON response. Amazon may depend on page HTML, browser-generated sessions, temporary tokens, or blocking behavior.

## Limitations
- Results reflect only configured live requests and saved files actually processed.
- Collected review counts are capped and must not be read as total source volume.
- Amazon findings in this run are based on three browser-captured AJAX response files parsed offline. They demonstrate parseability and sequential pagination, but do not establish unattended direct-request reliability.

## Preliminary Recommendation
Use Steam for the initial automated technical prototype because direct structured access and pagination were successfully demonstrated. Amazon browser-response parsing is also technically feasible and commercially broader, but unattended direct access remains unresolved. Continue Amazon only through a controlled browser-based or otherwise approved access proof of concept before selecting it for automated production ingestion.

## Suggested Next Step
1. Use Steam for the initial automated ingestion prototype.
2. Preserve the validated Amazon offline parser as a proof of parseability.
3. Conduct a separate controlled proof of concept for repeatable, approved Amazon access without manual Network copying.
4. Reassess Amazon for production ingestion only after access stability, compliance, and maintenance requirements are confirmed.
