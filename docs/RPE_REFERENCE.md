# RPE Reference — Rate of Perceived Exertion

This document provides the full RPE chart used by Strongman Coach, explains how e1RM (estimated 1-rep max) is calculated, and gives worked examples.

---

## What Is RPE?

RPE stands for **Rate of Perceived Exertion**. It is a subjective scale from 6 to 10 that tells you how hard a set felt — specifically, how many more reps you think you could have done (your "reps in reserve").

| RPE | Reps in Reserve (RIR) | Feeling |
|-----|-----------------------|---------|
| 6.0 | 4 reps left | Easy; you could have done 4 more |
| 6.5 | 3.5 reps left | Light |
| 7.0 | 3 reps left | Moderate; controlled |
| 7.5 | 2.5 reps left | Getting serious |
| 8.0 | 2 reps left | Hard but clean |
| 8.5 | 1.5 reps left | Very hard |
| 9.0 | 1 rep left | Near failure |
| 9.5 | 0.5 reps left | Almost maxed out |
| 10.0 | 0 reps left | Absolute failure |

Strongman Coach uses RPE in **0.5 steps** from 6.0 to 10.0. The app never prescribes above RPE 9.5 except on self-started test days.

---

## The RPE Percent Chart

Strongman Coach uses the standard Loengren / Ingjelsland RPE-to-%1RM table. Each cell shows what percentage of your true 1RM a given rep count at a given RPE represents.

### Full Chart (Reps 1–12 × RPE 6.0–10.0)

| Reps | RPE 6.0 | RPE 6.5 | RPE 7.0 | RPE 7.5 | RPE 8.0 | RPE 8.5 | RPE 9.0 | RPE 9.5 | RPE 10.0 |
|------|---------|---------|---------|---------|---------|---------|---------|---------|----------|
| 1    | 65.0%   | 70.0%   | 75.0%   | 80.0%   | 85.0%   | 88.0%   | 91.0%   | 95.0%   | 100.0%   |
| 2    | 71.0%   | 75.0%   | 78.0%   | 81.0%   | 84.0%   | 87.0%   | 89.0%   | 92.0%   | 95.0%   |
| 3    | 75.0%   | 78.0%   | 81.0%   | 84.0%   | 86.0%   | 88.0%   | 89.2%   | 92.0%   | 94.0%   |
| 4    | 78.0%   | 80.0%   | 83.0%   | 85.0%   | 87.0%   | 89.0%   | 91.0%   | 93.0%   | 95.0%   |
| 5    | 80.0%   | 82.0%   | 84.0%   | 86.0%   | 88.0%   | 89.0%   | 91.0%   | 93.0%   | 95.0%   |
| 6    | 82.0%   | 84.0%   | 86.0%   | 88.0%   | 89.0%   | 91.0%   | 93.0%   | 94.0%   | 96.0%   |
| 7    | 84.0%   | 86.0%   | 87.0%   | 89.0%   | 90.0%   | 92.0%   | 93.0%   | 95.0%   | 96.0%   |
| 8    | 85.0%   | 87.0%   | 88.0%   | 90.0%   | 91.0%   | 92.0%   | 94.0%   | 95.0%   | 96.0%   |
| 9    | 86.0%   | 87.0%   | 89.0%   | 90.0%   | 91.0%   | 93.0%   | 94.0%   | 95.0%   | 96.0%   |
| 10   | 87.0%   | 88.0%   | 89.0%   | 91.0%   | 92.0%   | 93.0%   | 94.0%   | 95.0%   | 96.0%   |
| 11   | 88.0%   | 89.0%   | 90.0%   | 91.0%   | 92.0%   | 93.0%   | 95.0%   | 96.0%   | 97.0%   |
| 12   | 89.0%   | 90.0%   | 91.0%   | 92.0%   | 93.0%   | 94.0%   | 95.0%   | 96.0%   | 96.0%   |

> **Source:** Loengren et al., *"The Relationship Between Repetitions to Exhaustion and Percentage of One-Repetition Maximum"* (2015), combined with the standard RPE-to-%1RM table used in strength coaching.

---

## How e1RM Is Calculated

**e1RM** (estimated 1-rep max) is computed from every set you log using the formula:

```
e1RM = weight ÷ (percent / 100)
```

Where `percent` is looked up from the chart above based on your reps and RPE.

### Step-by-Step Example

You log a set of **5 reps at 225 lb with RPE 8.0**.

1. Look up the chart: 5 reps × RPE 8.0 → **88.0%**
2. Calculate: e1RM = 225 ÷ 0.88 = **255.7 lb**

Your estimated 1-rep max from that set is **255.7 lb**.

### Another Example

You log **3 reps at 315 lb with RPE 9.0**.

1. Look up the chart: 3 reps × RPE 9.0 → **89.2%**
2. Calculate: e1RM = 315 ÷ 0.892 = **353.1 lb**

---

## Confidence Ratings

Not all e1RM values are equally reliable. Strongman Coach marks each set as **high confidence** or **low confidence**:

| Condition | Confidence |
|-----------|-----------|
| RPE ≥ 7.0 **and** reps ≤ 8 | **High** — the e1RM is a solid estimate |
| RPE < 7.0 | **Low** — the set was too easy to estimate a max |
| Reps > 8 | **Low** — high-rep sets are less predictive of 1RM |
| No RPE logged | **Low** — falls back to the Epley formula |

Only **high-confidence** sets are used to determine your session e1RM (the best e1RM from that session for a given lift).

---

## Epley Fallback

When you log a set **without an RPE**, Strongman Coach uses the Epley formula as a fallback:

```
e1RM = weight × (1 + reps / 30)
```

This is always marked **low confidence**. For example, 225 lb × 5 reps with no RPE:

```
e1RM = 225 × (1 + 5/30) = 225 × 1.167 = 262.5 lb  (low confidence)
```

The Epley formula is a rough estimate. Logging RPE gives a much more accurate e1RM.

---

## Target Load Calculation

When the app tells you to lift a certain weight, it works backwards from your e1RM:

```
target_load = e1RM × (percent / 100)
```

The result is rounded **down** to the nearest plate increment (default 2.5 lb).

### Example

Your e1RM for deadlift is **340 lb**. The prescription is **5 reps @ RPE 8.0**.

1. Chart lookup: 5 reps × RPE 8.0 → **88.0%**
2. Raw load: 340 × 0.88 = **299.2 lb**
3. Rounded down to 2.5 lb increment: **297.5 lb**

The app prescribes **297.5 lb** for your top set.

---

## Quick Reference: Common Prescriptions

Here are some typical main-lift prescriptions and their chart values:

| Reps | RPE | % of 1RM | Typical Use |
|------|-----|----------|-------------|
| 5    | 7.5 | 86.0%    | Accumulation, early cycle |
| 5    | 8.0 | 88.0%    | Accumulation, mid cycle |
| 4    | 8.5 | 89.0%    | Accumulation, late cycle |
| 4    | 8.0 | 87.0%    | Intensification, early cycle |
| 3    | 8.5 | 88.0%    | Intensification, mid cycle |
| 3    | 9.0 | 91.0%    | Intensification, late cycle |
| 3    | 8.5 | 88.0%    | Realization, early cycle |
| 2    | 9.0 | 89.0%    | Realization, mid cycle |
| 2    | 9.5 | 92.0%    | Realization, late cycle |

---

## Tips for Rating RPE Accurately

1. **Be honest.** If you could have done 2 more reps, that's RPE 8.0 — not RPE 9.0.
2. **Consistency matters more than precision.** It's fine if you're off by 0.5; the app adjusts. What matters is that you rate similarly each session.
3. **When in doubt, round down.** It's safer to under-rate than over-rate. The app will nudge you heavier next session if you consistently come in light.
4. **Fatigue affects RPE.** A set that felt like RPE 8.0 on Day A might feel like RPE 9.0 on Day C if you're accumulated fatigue. That's normal — the app accounts for it.
