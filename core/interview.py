"""Interview practice questions for one job, from the CV and the job description (own code, no AI).

Every question has a tip. When the CV covers something the job asks for, the question shows
the CV line so the person is ready to explain it. When the CV does not cover it, the tip
says to answer honestly and never claim it.
"""

MAX_QUESTIONS = 14
MAX_ANSWER = 2000


def questions(parsed, analysis, title="", company=""):
    qs = []
    edu = [i["text"] for s in parsed["sections"] if s["key"] == "education" for i in s["items"]]
    work = [i["text"] for s in parsed["sections"] if s["key"] in ("projects", "experience") for i in s["items"]]
    qs.append({"id": "intro", "kind": "general", "question": "Tell me about yourself.",
               "tip": "Three parts, about one minute: who you are (your education), what you have done (one project or job), and why this role.",
               "cv_line": edu[0] if edu else ""})
    role = title.strip() or "this role"
    qs.append({"id": "why", "kind": "general",
               "question": "Why do you want to work as %s%s?" % (role, " at %s" % company.strip() if company.strip() else ""),
               "tip": "Read the job description again. Name two things in it that you really like, and connect each to something you have done.",
               "cv_line": ""})
    cov = sorted(analysis["covered"], key=lambda c: (not c["required"], c["term"]))
    for c in cov[:4]:
        qs.append({"id": "has:" + c["term"], "kind": "from your CV",
                   "question": "The job asks for %s. Tell me about a time you used it." % c["name"],
                   "tip": "Use STAR: Situation, Task, Action, Result. Give one real example with a number if you have one.",
                   "cv_line": c["line"]})
    miss = [m for m in analysis["missing"] if m["required"]]
    for m in miss[:3]:
        qs.append({"id": "gap:" + m["term"], "kind": "gap",
                   "question": "This job asks for %s. How much have you done with it?" % m["name"],
                   "tip": "Your CV does not show this. Be honest: say what you have not done, then what close thing you have done or are learning. Never claim it.",
                   "cv_line": ""})
    for n, line in enumerate(work[:2]):
        qs.append({"id": "line%d" % n, "kind": "from your CV", "question": "Walk me through this: what was your part and what was hard?",
                   "tip": "They will ask about anything written on your CV. Know every number and tool in this line.", "cv_line": line})
    qs.append({"id": "mistake", "kind": "behaviour", "question": "Tell me about a mistake you made and what you learned.",
               "tip": "Pick a small real mistake, say what you changed after it. Do not blame others.", "cv_line": ""})
    qs.append({"id": "deadline", "kind": "behaviour", "question": "How do you work when a deadline is close?",
               "tip": "Give a real example: how you decided what first, and how you told your team.", "cv_line": ""})
    qs.append({"id": "ask", "kind": "general", "question": "Do you have any questions for us?",
               "tip": "Prepare two real questions, for example about the team, what the first three months look like, or how work is reviewed.",
               "cv_line": ""})
    return qs[:MAX_QUESTIONS]
