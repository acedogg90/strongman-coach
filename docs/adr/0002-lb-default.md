# ADR-0002: Pounds (lb) as Default Units

## Status
Accepted

## Context
Strongman training in the US uses pounds. The athlete may prefer kg, but all internal calculations (RPE chart, e1RM, plate math) are defined in pounds.

## Decision
Pounds (lb) is the default unit. A kg toggle exists in settings. Conversion happens only at display and input boundaries; all internal calculations use lb.

## Consequences
- The RPE chart and e1RM formulas need no unit-aware logic.
- Plate increments (2.5 lb) are natural in lb.
- kg users see converted values but the DB stores lb.
