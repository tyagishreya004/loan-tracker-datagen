# AI usage disclosure

**Tool:** Claude (Anthropic), via claude.ai chat with code execution.

**Where AI accelerated work:** the first full implementation of `schema.py`, `rules.py`, `generate.py`, `validate.py`,
`evaluate.py`, `repro_check.py`, and drafts of README/DESIGN, produced from the challenge problem statement.
Claude also ran the pipeline, tuned the distributions (initial run: ~30% high-DTI declines, too few approvals) and
found a bug through the validator (employment end before start).

**Where I relied heavily on AI:** nearly all code and documentation text.

**What I personally reviewed / changed / validated:** 
> TODO (candidate must complete honestly before submitting): e.g. read every module; re-ran `./run_all.sh`;
> inspected sample rows and decisions; changed thresholds/products/anomaly counts; verified a few decisions by hand;
> list anything you altered. Be ready to walk through rules.py, the injection logic and the validator.

**Prompt history:** see `PROMPT_HISTORY.md`.
