"""Phone-size check of every screen (needs: pip install playwright; playwright install chromium).

Start the app first (DEBUG=1 python manage.py runserver 8011), then:
    python tests/mobile_audit.py 360     # or 390
Prints, per screen: sideways overflow, tap targets under 40 px, input text under 16 px (iPhone zooms in below 16),
and saves screenshots to the folder given as 3rd argument (default: current folder).
The tab buttons are meant to scroll sideways, so "wide: button.tab" is expected.
"""
import os, sys, random, json
from playwright.sync_api import sync_playwright
W=int(sys.argv[1]) if len(sys.argv)>1 else 360
H=740 if W<380 else 844
tag="m"
OUT=sys.argv[2] if len(sys.argv)>2 else "."
email="mob%d@example.com"%random.randint(1000,999999)
JD="Python developer. Must have experience with Django and REST APIs. Knowledge of Docker is required. You will write test cases."
AUDIT="""() => {
  const vw = document.documentElement.clientWidth, out = {over: document.documentElement.scrollWidth - vw, wide: [], tiny: [], smallfont: []};
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el); if (cs.visibility==='hidden'||cs.display==='none') continue;
    const name = el.tagName.toLowerCase() + (el.id?'#'+el.id:'') + (el.className&&typeof el.className==='string'?'.'+el.className.split(' ').join('.'):'');
    if (r.right > vw + 1 && !el.closest('iframe')) out.wide.push(name + ' right=' + Math.round(r.right));
    const tag = el.tagName;
    if (['BUTTON','SELECT','INPUT','A'].includes(tag) && el.type!=='hidden' && (r.height < 40 || (r.width < 40 && tag!=='A'))) out.tiny.push(name + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' "' + (el.innerText||el.value||'').slice(0,20) + '"');
    if (['INPUT','SELECT','TEXTAREA'].includes(tag) && parseFloat(cs.fontSize) < 16) out.smallfont.push(name + ' ' + cs.fontSize);
  }
  return out;
}"""
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":W,"height":H}, device_scale_factor=2, is_mobile=True, has_touch=True); pg=ctx.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    report={}
    def audit(name, full=True):
        pg.wait_for_timeout(500)
        report[name]=pg.evaluate(AUDIT)
        pg.screenshot(path=os.path.join(OUT,"m_%s_%s.png"%(W,name)), full_page=full)
    pg.goto("http://localhost:8011/"); pg.wait_for_timeout(700); audit("login")
    pg.get_by_text("Create account").first.click() if pg.get_by_text("Create account").count() else None
    pg.wait_for_timeout(300)
    pg.fill("#name","Aarti Sharma"); pg.fill("#email",email); pg.fill("#password","Strong-pass-77x-ok"); pg.check("#terms"); audit("register")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200); audit("cv_empty")
    pg.get_by_text("Build my CV from scratch").click(); audit("wiz1")
    pg.fill("#w-name","Aarti Sharma"); pg.fill("#w-email","aarti@example.com"); pg.fill("#w-phone","+91 98200 11122"); pg.get_by_role("button",name="Next").click()
    pg.get_by_role("button",name="Next").click(); audit("wiz_edu")
    pg.fill("#w-education0degree","MCA"); pg.fill("#w-education0school","Mumbai University"); pg.get_by_role("button",name="Next").click()
    pg.fill("#w-skills0items","Python, Django"); pg.get_by_role("button",name="Next").click()
    pg.fill("#w-projects0title","ResumeWise"); pg.fill("#w-projects0points","Wrote 254 test cases\nBuilt REST APIs in Django"); audit("wiz_proj")
    for _ in range(3): pg.get_by_role("button",name="Next").click()
    audit("wiz_review")
    pg.get_by_role("button",name="Create my CV").click(); pg.wait_for_timeout(1800); audit("templates")
    pg.get_by_role("tab",name="1. My CV").click(); audit("cv")
    pg.get_by_role("tab",name="3. Tailor to a job").click(); audit("tailor")
    pg.get_by_role("tab",name="4. Jobs").click(); pg.fill("#j-title","Python Developer"); pg.fill("#j-company","Acme"); pg.fill("#j-text",JD); audit("jobs")
    pg.get_by_role("button",name="Save job and check match").click(); pg.wait_for_timeout(1200); audit("job_detail")
    pg.get_by_role("button",name="Write cover letter").click(); pg.wait_for_timeout(500)
    pg.get_by_role("button",name="Show practice questions").click(); audit("job_full")
    pg.get_by_role("tab",name="5. Account").click(); audit("account")
    print(json.dumps({k:{kk:(vv if kk=='over' else vv[:6]) for kk,vv in v.items()} for k,v in report.items()},indent=1))
    print("ERRS",errs)
