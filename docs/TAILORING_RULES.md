# AI tailoring: must-have rules

These apply to the first AI tailoring step. Items 1 to 4 are already coded in `core/`.

1. **Only the user's facts.** Every line has a `source_id` or is marked New and confirmed by the user (`core/tailoring.py`, `core/verifier.py`).
2. **Minimal change.** Keep the user's own words. A "reworded" line that keeps less than 60% of the original's words is flagged (`core/style.py`, `keep_ratio`).
3. **No stock phrases.** Words like "spearheaded", "leveraged", "passionate" are flagged unless the user wrote them (`core/style.py`, `find_cliches`).
4. **The user's own style.** New lines are compared with the user's line length, full-stop habit and number use (`core/style.py`, `style_profile`).
5. **Edit before export.** The user reads and can rewrite every New or reworded line (My CV editor and review screen).
6. **Instructions for the AI** (to put in the gateway call when it is built): keep the user's wording where it already fits the job; reword only to add a job keyword the user really has; do not add adjectives, numbers or tools that are not in the source line; match the length and punctuation of the user's other lines; return JSON in the `core/tailoring.py` shape.
7. **Honest messaging.** The product never says it beats AI detectors. It says: built on your facts, in your words.
8. **User note.** Before applying, remind the user to read the form's rules, since some ask to disclose AI help.

Style warnings go to the review screen. They do not block a line by themselves; the user decides.
