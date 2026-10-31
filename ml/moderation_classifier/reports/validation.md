# Validation report

1971 examples from 279 templates, scored with 5-fold cross-validation grouped by template: each message was scored by a model that never saw its template.

Targets: missed harmful ≤ 2%, false blocks ≤ 5%. Chosen threshold: **0.80** (the lowest that meets both, so the fewest messages wait for tier 3).

## Threshold sweep

| Threshold | Escalated to tier 3 | Missed harmful | False blocks | Accuracy when deciding |
|---|---|---|---|---|
| 0.50 | 10.0% | 6.6% | 9.3% | 86.6% |
| 0.55 | 13.5% | 5.7% | 7.9% | 87.7% |
| 0.60 | 18.5% | 4.9% | 5.9% | 89.1% |
| 0.65 | 23.4% | 3.9% | 4.8% | 90.5% |
| 0.70 | 28.9% | 2.7% | 3.9% | 91.9% |
| 0.75 | 33.3% | 2.2% | 3.1% | 92.8% |
| 0.80 ✅ | 39.8% | 1.8% | 2.6% | 93.8% |
| 0.85 | 48.7% | 0.9% | 2.0% | 95.4% |
| 0.90 | 60.1% | 0.2% | 1.2% | 97.0% |
| 0.95 | 77.5% | 0.0% | 0.4% | 98.4% |

## Confusion matrix (top label, before the threshold)

| true ↓ / predicted → | safe | prompt_injection | social_engineering | abuse | distress | off_topic |
|---|---|---|---|---|---|---|
| **safe** | 670 | 0 | 29 | 7 | 11 | 46 |
| **prompt_injection** | 15 | 234 | 5 | 10 | 0 | 0 |
| **social_engineering** | 33 | 7 | 207 | 0 | 0 | 5 |
| **abuse** | 5 | 7 | 0 | 218 | 10 | 0 |
| **distress** | 40 | 0 | 4 | 0 | 180 | 0 |
| **off_topic** | 88 | 3 | 1 | 6 | 1 | 129 |

## Per label

| Label | Precision | Recall | Examples |
|---|---|---|---|
| safe | 79% | 88% | 763 |
| prompt_injection | 93% | 89% | 264 |
| social_engineering | 84% | 82% | 252 |
| abuse | 90% | 91% | 240 |
| distress | 89% | 80% | 224 |
| off_topic | 72% | 57% | 228 |
