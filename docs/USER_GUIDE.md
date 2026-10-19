# Strongman Coach — User Guide

This guide explains how to use Strongman Coach, a phone-first training app that plans and adjusts strongman-style strength training using RPE (Rate of Perceived Exertion). If you know how to lift but have never used an autoregulation system, this is the document for you.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Starting and Completing a Workout Session](#2-starting-and-completing-a-workout-session)
3. [Understanding RPE and e1RM](#3-understanding-rpe-and-e1rm)
4. [How APRE Works for Secondary Lifts](#4-how-apre-works-for-secondary-lifts)
5. [Adjustment Rules — How the App Adapts to You](#5-adjustment-rules--how-the-app-adapts-to-you)
6. [Using the Dashboard](#6-using-the-dashboard)
7. [Configuring Settings](#7-configuring-settings)
8. [Offline Use](#8-offline-use)
9. [Exporting Your Data](#9-exporting-your-data)

---

## 1. Getting Started

Strongman Coach runs as a web app on your phone. Install it to your home screen for the best experience:

1. Open the app in your phone's browser.
2. Tap the browser menu and select **"Add to Home Screen"** (iOS) or **"Install app"** (Android).
3. Launch it from your home screen like any other app.

The app works **offline** — you can log workouts at the gym even without internet. Data syncs when you reconnect to your home network.

### Your First Steps

- **Set up your athlete profile**: name, height, age, training age, and units (pounds or kilograms).
- **Check your equipment inventory**: the app seeds a default list based on a typical gym. Uncheck items you don't have; exercises requiring unavailable equipment are hidden automatically.
- **Start a program**: the app generates a 4-day training cycle (Days A, B, C, D) with main lifts, secondary lifts, accessories, and strongman events.

---

## 2. Starting and Completing a Workout Session

### Opening a Session

1. From the home screen, tap the session you want to train (e.g., "Day A — Deadlift").
2. The **readiness check** appears first (optional but recommended). Rate your sleep, soreness, and stress on a 1–5 scale. A low score (1 or 2) suggests — but does not force — dropping your top-set RPE target by 0.5 for the day.
3. Tap **Start Session** to begin.

### Logging Sets

The logging screen is designed for one-handed use in the gym:

1. **Warm-up sets** are shown first. Log each warm-up with weight and reps. RPE is optional for warm-ups.
2. **Top set** is your main working set. The app shows the prescribed weight and target RPE.
   - Enter the **actual weight** you lifted.
   - Enter the **actual reps** completed.
   - Select your **RPE** using the 0.5-step picker (6.0 through 10.0).
   - Optionally add a **note** (e.g., "felt strong," "bar speed slow").
   - Toggle the **pain flag** if something hurts (this stops further sets of that exercise for the day — see [Adjustment Rules](#5-adjustment-rules--how-the-app-adapts-to-you)).
3. **Back-off sets** appear after your top set if your RPE was at or below the target. The app shows the reduced load for each back-off set. Log them the same way. Back-offs are capped at 6 total sets (including the top set).
4. After finishing all exercises, tap **Complete Session**. The app recalculates your e1RM trends and adjusts upcoming sessions.

### Events

Strongman events (yoke, atlas stones, farmers walk, etc.) are logged differently depending on the metric type:

| Metric Type | What You Log |
|-------------|-------------|
| `load_distance` | Weight carried and distance covered |
| `load_time` | Weight carried and time completed |
| `reps_in_time` | Number of reps completed in a time window |

### Rest Timer

A rest timer starts automatically after each set. It vibrates when the rest period ends so you can keep your phone face-down.

### Session e1RM Display

After each exercise, the screen shows your **session e1RM** (the best high-confidence e1RM from that session) alongside your **trend e1RM** (your rolling average). This lets you see immediately whether you're on track.

---

## 3. Understanding RPE and e1RM

### What Is RPE?

**RPE** (Rate of Perceived Exertion) is a scale from 6 to 10 that tells you how hard a set felt — specifically, how many more reps you think you could have done.

| RPE | Reps in Reserve | Feeling |
|-----|----------------|---------|
| 6.0 | 4 reps left | Easy |
| 7.0 | 3 reps left | Moderate |
| 8.0 | 2 reps left | Hard but clean |
| 9.0 | 1 rep left | Near failure |
| 9.5 | 0.5 reps left | Almost maxed out |
| 10.0 | 0 reps left | Absolute failure |

The app uses 0.5 steps (6.0, 6.5, 7.0, …, 10.0). It **never prescribes above RPE 9.5** except on test days you start yourself.

> **Tip:** Consistency matters more than precision. If you're off by 0.5, the app adjusts. What matters is rating similarly each session. When in doubt, round down.

### What Is e1RM?

**e1RM** (estimated 1-rep max) is what the app calculates for every set you log. Instead of guessing your max, the app uses the weight, reps, and RPE you report to estimate it using a validated percentage chart.

**How it works:**

1. You log: 5 reps at 225 lb, RPE 8.0.
2. The app looks up the chart: 5 reps × RPE 8.0 = **88.0%** of your 1RM.
3. It calculates: e1RM = 225 ÷ 0.88 = **255.7 lb**.

Your estimated max from that single set is 255.7 lb. Over multiple sessions, the app builds a trend.

### Confidence Ratings

Not all sets are equally reliable for estimating your max:

| Condition | Confidence |
|-----------|-----------|
| RPE ≥ 7.0 and reps ≤ 8 | **High** — solid estimate |
| RPE < 7.0 | **Low** — set was too easy |
| Reps > 8 | **Low** — high-rep sets are less predictive |
| No RPE logged | **Low** — falls back to the Epley formula |

Only **high-confidence** sets count toward your session e1RM.

### Epley Fallback

If you forget to log RPE, the app uses the Epley formula as a rough estimate:

```
e1RM = weight × (1 + reps / 30)
```

This is always marked low confidence. Logging RPE gives a much more accurate result.

> **Full chart and more examples:** See [RPE_REFERENCE.md](RPE_REFERENCE.md) for the complete RPE percentage chart, worked examples, and tips for accurate RPE rating.

---

## 4. How APRE Works for Secondary Lifts

### What Is APRE?

**APRE** stands for **Adaptive Periodization by Rep Exhaustion**. It is the method Strongman Coach uses for secondary lifts (accessories that support your main lifts but aren't the primary focus).

### How It Works

Instead of prescribing a fixed weight, APRE starts you at a **percentage of your estimated 6-rep max (6RM)** and adjusts based on how many reps you actually complete:

1. **First set (6RM set):** You lift at a prescribed percentage of your 6RM. The goal is to complete as many reps as possible with good form (up to a cap).
2. **Second set (3RM set):** Based on how many reps you got on the first set, the app adjusts the load for the second set using a lookup table. If you hit more reps than expected, the load goes up. If you hit fewer, it goes down.
3. **Subsequent sets:** The same adjustment logic applies. Each set's load is determined by your performance on the previous set.

### Why APRE?

APRE ensures you're always training at the right intensity for how you feel that day. If you're fresh, you'll naturally hit more reps and the load increases. If you're fatigued, the load decreases. This is **autoregulation** — the program adapts to you, not the other way around.

### Load Adjustment Between Sessions

After each session, the app recalculates your e1RM for secondary lifts. Your next session's starting percentage is based on your updated e1RM, so the loads automatically scale with your progress.

---

## 5. Adjustment Rules — How the App Adapts to You

Strongman Coach has four built-in adjustment rules that modify your upcoming sessions based on how you actually performed. These run automatically when you complete a session.

### Rule 1: RPE Too High

**Trigger:** Your top-set RPE is **1.0 or more above** the prescribed target (e.g., prescribed RPE 8.0 but you logged RPE 9.0+).

**What happens:**
- Back-off sets are **skipped** — you're already done.
- Your next session's load for that exercise is **reduced** slightly so the prescribed RPE is more accurate.

**Why:** If the weight felt heavier than planned, the app backs off to keep you in the right intensity zone.

### Rule 2: RPE Too Low

**Trigger:** Your top-set RPE is **1.0 or more below** the prescribed target (e.g., prescribed RPE 8.0 but you logged RPE 7.0 or lower).

**What happens:**
- The app **offers a heavier top set** in the next session.
- The increase is modest: **+2.5 lb for presses**, **+5 lb for squats and deadlifts**.

**Why:** If the weight felt lighter than planned, the app nudges you heavier so you keep progressing.

### Rule 3: e1RM Stall

**Trigger:** Your **trend e1RM** (the average of your best 2 of the last 3 sessions) has **not improved** compared to 3 cycles ago.

**What happens:**
- An **early deload** is triggered for that exercise.
- The app may also **swap the exercise variation** (e.g., conventional deadlift → deficit deadlift) to provide a fresh stimulus.

**Why:** Stalls are normal. The app responds by reducing fatigue and changing the stimulus rather than pushing through.

### Rule 4: Pain Flag

**Trigger:** You toggle the **pain flag** on any set.

**What happens:**
- All further sets of that exercise are **immediately stopped** for the rest of the session.
- No adjustment is made to future sessions — the app simply respects that you need to stop.

**Why:** Safety first. Pain is a signal to stop, not push through. The app never overrides this.

---

## 6. Using the Dashboard

The dashboard gives you a bird's-eye view of your progress. Access it from the home screen.

### Trend e1RM Per Lift

For each main lift, the dashboard shows:

- **Trend e1RM:** The rolling average of your best 2 of the last 3 sessions. This smooths out day-to-day noise and shows your true direction.
- **Bodyweight multiple:** Your trend e1RM divided by your current bodyweight (e.g., 1.5× bodyweight on bench press). This lets you track strength relative to your size.
- **e1RM over time chart:** A line chart showing your session e1RM for each lift over time. Look for an upward trend over weeks, not day-to-day jumps.

### Interpreting e1RM Trends

- **Upward trend:** You're progressing. Keep following the program.
- **Flat trend (3+ cycles):** The app flags this as a stall and may trigger a deload or variation swap.
- **Downward trend:** You may be accumulating fatigue. Consider extra rest or a deload week.

### Weekly Tonnage Chart

A bar chart showing total tonnage (weight × reps) per movement pattern (hinge, squat, press, carry, etc.) each week. This helps you see whether your volume is balanced across patterns.

### Next 5 Sessions Preview

A list of your upcoming sessions with prescribed exercises and loads. This lets you plan your week ahead and see how adjustments from recent sessions have shifted your loads.

### Personal Records (PRs)

The dashboard tracks three types of PRs:

| PR Type | What It Means |
|---------|-------------|
| True 1RM | Your actual single-rep max (logged at RPE 10.0) |
| e1RM | Your highest estimated 1RM from any set |
| Rep PR | Most reps completed at a given weight |

### Benchmarks

The dashboard includes a **Benchmarks table** seeded with ASM (American Strongman) 2025 values. For each lift, it shows:

- Your current trend e1RM
- The benchmark value for your weight class
- **Percent of benchmark** — how close you are to the standard

You can edit benchmark values in settings if you want different targets.

### Stall Detection

The dashboard flags any exercise where your trend e1RM has not improved in 3+ cycles. This is informational — the app already handles stalls by triggering deloads and variation swaps automatically.

---

## 7. Configuring Settings

Access settings from the home screen menu.

### Athlete Profile

| Field | Description |
|-------|-------------|
| Name | Your display name |
| Height | In centimeters |
| Age | Used to determine weight class (amateur vs. masters) |
| Training Age | Months of consistent training |
| Units | Pounds (lb) or kilograms (kg). Default is lb. |
| Plate Increment | Default 2.5 lb. Change if your plates differ. |
| Dumbbell Max | Default 120 lb. Used to filter accessible exercises. |

### Equipment Inventory

A checklist of all available equipment, organized into three categories:

- **Gym equipment:** Seeded from a typical Crunch Fitness inventory.
- **Club items:** Turf, sled, tires, landmines, kettlebells, medicine balls.
- **Personal gear:** Sandbag, fat grips, straps, belt, chalk.

Uncheck items you don't have. Exercises requiring unavailable equipment are hidden automatically, and the planner offers substitutes where possible.

### Weight Class

The app selects your weight class based on your age:

- **Amateur (under 40):** 80 / 90 / 105 / 120 kg / Heavyweight (over 120 kg)
- **Masters (40+):** 80 / 90 / 105 kg / Heavyweight (over 105 kg)

This determines which benchmark values are shown on the dashboard.

### Safety Notice

On your first visit to settings, a **"not medical advice"** notice is displayed. Acknowledge it to dismiss. It is stored and not shown again.

### Benchmarks

You can edit the benchmark values for each lift if you want different targets than the default ASM 2025 values.

---

## 8. Offline Use

Strongman Coach is designed to work in the gym even without internet:

- The app shell (HTML, CSS, JS) is cached on your phone after the first install.
- When you log sets offline, they are stored in your phone's local storage (IndexedDB).
- The UI shows your data immediately — you never see a blank screen.
- When you reconnect to your home network, queued sets sync automatically to the server.
- If sync fails, the app retries with increasing delays (up to 3 attempts). Failed entries are flagged for manual review.

**Tip:** Make sure you're on the same LAN as the server for sync to work. No internet is needed — just the local network.

---

## 9. Exporting Your Data

From the settings menu, you can export all your training data:

- **CSV export:** Download a spreadsheet of every logged set and event.
- **JSON export:** Download structured data for use with other tools.
- **Printable block view:** A clean, printable HTML view of your current training block.

---

## Quick Reference

| Question | Answer |
|----------|--------|
| How do I start a workout? | Tap the session from the home screen, complete the readiness check, tap Start. |
| What if I forget RPE? | The app uses the Epley formula as a fallback (low confidence). |
| Can I go above RPE 9.5? | Only on test days you start yourself. The app never prescribes above 9.5. |
| What happens if I feel pain? | Toggle the pain flag — it stops that exercise for the day immediately. |
| How does the app adjust loads? | Four rules: RPE too high (reduce), RPE too low (increase), stall (deload), pain (stop). |
| Does it work offline? | Yes. Data syncs when you reconnect to your home network. |

---

*Strongman Coach is a training planning tool. It is not medical advice. Consult a qualified professional before making changes to your training program.*
