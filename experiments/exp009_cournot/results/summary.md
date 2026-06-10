# exp009 — Cournot few-shot marginal-cost summary

**Verdict=NO** — explicit few-shot marginal-cost examples DID NOT reduce deviation from the Nash quantity per the pre-registered rule.

mean_dev(explicit)=0.5000 is NOT < mean_dev(absent)=0.5000; mean_dev(explicit)=0.5000 exceeds the pre-registered ceiling 0.15.

## Per-treatment statistics

### absent

- trials: 50 (valid: 50, invalid: 0)
- mean |q - q*|/q*: 0.5000
- mean quantity: 45.00
- quantity variance: 0.00

### explicit

- trials: 50 (valid: 50, invalid: 0)
- mean |q - q*|/q*: 0.5000
- mean quantity: 45.00
- quantity variance: 0.00

## Secondary signal (directional, NOT verdict-bearing)

- var(explicit) < var(absent): False

## Pre-registered verdict rule

YES iff mean_dev(explicit) < mean_dev(absent) AND mean_dev(explicit) <= 0.15.

Errors: 0
