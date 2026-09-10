# Operator directives

This directory holds explicit, human-authored instructions for the surrounding
BenLab toolchain. A directive is a durable statement of intent, not an automatic
write into another repository or calendar.

Create a draft from the repository root:

```bash
python3 scripts/lab-console new-directive benlab \
  "Review the named Analyst candidate for promotion" \
  --type review_candidate \
  --source "analyst:card-example"
```

Every new directive starts as `draft` and has `requires_confirmation: true`.
Review the generated JSON before changing it to `approved`. There is deliberately
no dispatcher yet: a future adapter must validate approval, target authority, and
source freshness before it may write elsewhere.

The format is defined by [`../directive.schema.json`](../directive.schema.json).
