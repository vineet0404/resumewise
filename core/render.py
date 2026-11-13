"""Turn a parsed resume into a finished page in one of five templates.

Own code, no template engine. Every piece of user text goes through html.escape,
so nothing the user (or an uploaded file) wrote can run as a script. The only
non-text content is the photo, embedded as a data URI after core.image_check.

Templates:
  classic, modern, compact      no photo, plain layout
  photo_header                  photo at the top right, single column
  photo_sidebar                 two columns, the riskiest for scanners

Scanner rules these templates follow (checked by tests/test_ats.py):
  - no letter-spacing on headings (it makes scanners read "S U M M A R Y")
  - the name is the first text on the page, even in the sidebar template
  - one block of text per line item, no tables, no text inside images
"""

import base64
import html
import re

from . import profile_edit

TEMPLATES = {
    "classic": {
        "name": "Classic", "photo": False, "ats_friendly": True,
        "description": "Serif font, centred name, thin lines. The most formal.",
    },
    "modern": {
        "name": "Modern", "photo": False, "ats_friendly": True,
        "description": "Green headings and a clean single column. Good for freshers.",
    },
    "compact": {
        "name": "Compact", "photo": False, "ats_friendly": True,
        "description": "Smaller text, two columns at the bottom. Fits more on one page.",
        "ats_note": "Skills and education sit in two columns at the bottom.",
    },
    "photo_header": {
        "name": "Photo header", "photo": True, "ats_friendly": True,
        "description": "Your photo at the top right, single column below.",
        "ats_note": "Text reads cleanly in our test; scanners ignore the photo itself.",
    },
    "photo_sidebar": {
        "name": "Photo sidebar", "photo": True, "ats_friendly": False,
        "description": "Round photo and contact details in a green side bar.",
        "ats_note": "Two columns: some scanners read across both columns.",
    },
}
DEFAULT_TEMPLATE = "classic"

MAIN_ORDER = ("summary", "experience", "projects", "skills", "education",
              "certifications", "achievements", "languages", "interests")
# The side bar holds only the photo and contact details. Skills and education stay in the main
# column so the page text keeps the resume order (name, contact, then the sections).
SIDEBAR_KEYS = ()
_PHOTO_TYPES = ("image/jpeg", "image/png")
_LINE_LIST_KEYS = ("skills", "languages", "interests")

_e = html.escape


def list_templates():
    return [dict(id=k, **v) for k, v in TEMPLATES.items()]


def _name_and_role(parsed):
    return profile_edit.name_and_role(parsed)


def _initials(name):
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return "".join(p[0].upper() for p in parts[:2]) or "?"


def _contact_lines(contact):
    first = " | ".join(x for x in (contact.get("location"), contact.get("email"), contact.get("phone")) if x)
    second = " | ".join(contact.get("links", []))
    return [x for x in (first, second) if x]


def _photo_html(photo, name, css_class):
    if photo is None:
        return '<div class="%s ph-empty" aria-hidden="true">%s</div>' % (css_class, _e(_initials(name)))
    if photo.get("content_type") not in _PHOTO_TYPES:
        raise ValueError("unsupported photo type")
    encoded = base64.b64encode(photo["data"]).decode("ascii")
    return '<img class="%s" alt="Profile photo" src="data:%s;base64,%s">' % (css_class, photo["content_type"], encoded)


def _sections(parsed):
    """{key: (title, [lines])} in the order the resume has them."""
    result = {}
    for section in parsed.get("sections", []):
        title = profile_edit.SECTION_TITLES.get(section["key"], section.get("title") or section["key"].upper())
        result[section["key"]] = (title, [item["text"] for item in section["items"]])
    return result


def _section_html(key, title, lines, tag="h2"):
    head = "<%s>%s</%s>" % (tag, _e(title), tag)
    if key == "summary":
        return head + "<p>%s</p>" % _e(" ".join(lines))
    if key in _LINE_LIST_KEYS:
        return head + "".join("<div class='ln'>%s</div>" % _e(t) for t in lines)
    return head + "<ul>" + "".join("<li>%s</li>" % _e(t) for t in lines) + "</ul>"


def _ordered_keys(sections, allowed=None, skip=()):
    keys = [k for k in MAIN_ORDER if k in sections]
    keys += [k for k in sections if k not in MAIN_ORDER]
    return [k for k in keys if k not in skip and (allowed is None or k in allowed)]


_BASE_CSS = (
    "*{box-sizing:border-box}html{-webkit-print-color-adjust:exact;print-color-adjust:exact}"
    "body{margin:0;background:#E9ECEA;color:#1a1a1a;font-family:Arial,Helvetica,sans-serif}"
    ".page{width:794px;min-height:1123px;margin:0 auto;background:#fff;position:relative}"
    "p,li{margin:0;line-height:1.55}ul{margin:4px 0 8px;padding-left:18px}li{margin-bottom:3px}"
    ".ln{margin:3px 0;line-height:1.5}h1,h2,h3{margin:0}"
    "@page{size:A4;margin:0}@media print{body{background:#fff}.page{margin:0;width:auto;min-height:0}}"
)

_CSS = {
    "classic": ".page{padding:52px 60px;font-family:Georgia,'Times New Roman',serif}.page *{font-size:12.5px}"
               "h1{text-align:center;font-size:28px!important;font-weight:normal}"
               ".ct{text-align:center;color:#333;margin-top:8px;line-height:1.6}"
               "h2{margin:20px 0 6px;border-bottom:1px solid #000;padding-bottom:2px}",
    "modern": ".page{padding:48px 56px}.page *{font-size:12px}h1{font-size:30px!important}"
              ".role{margin-top:4px;color:#0E6B5C;font-weight:bold;font-size:14px!important}"
              ".ct{margin-top:8px;color:#444;line-height:1.6;font-size:11.5px!important}"
              "h2{margin:22px 0 6px;color:#0E6B5C;border-bottom:1.5px solid #0E6B5C;padding-bottom:3px}",
    "compact": ".page{padding:34px 40px}.page *{font-size:10.8px}h1{font-size:24px!important;display:inline}"
               ".role{display:inline;margin-left:10px;color:#444;font-size:13px!important}"
               ".ct{margin-top:4px;color:#444;line-height:1.5}"
               "h2{margin:13px 0 4px;background:#EEF1EF;padding:3px 8px;border-left:4px solid #0E6B5C}"
               "li{margin-bottom:1px}.cols{display:flex;gap:28px}.cols>div{flex:1}",
    "photo_header": ".page{padding:48px 56px}.page *{font-size:12px}"
                    ".head{display:flex;justify-content:space-between;align-items:center;gap:20px;"
                    "border-bottom:3px solid #0E6B5C;padding-bottom:16px}h1{font-size:30px!important}"
                    ".role{margin-top:4px;color:#0E6B5C;font-weight:bold;font-size:14px!important}"
                    ".ct{margin-top:8px;color:#444;line-height:1.6;font-size:11.5px!important}"
                    ".ph{width:118px;height:140px;border-radius:10px;object-fit:cover;border:2px solid #E2E7E4;flex:none}"
                    ".ph-empty{display:flex;align-items:center;justify-content:center;background:#D9E4E0;"
                    "color:#5E7A72;font-size:34px!important;font-weight:bold}"
                    "h2{margin:20px 0 6px;color:#0E6B5C}",
    "photo_sidebar": ".page{padding-left:262px}.side{position:absolute;left:0;top:0;bottom:0;width:262px;background:#0E4F45;color:#fff;padding:40px 24px}"
                     ".side *{font-size:11.5px}.main{padding:44px 40px}.main.top{padding-bottom:0}.main.rest{padding-top:6px}.main *{font-size:12px}"
                     ".ph{width:128px;height:128px;border-radius:50%;object-fit:cover;display:block;"
                     "margin:0 auto 22px;border:4px solid #7CC4B4}"
                     ".ph-empty{display:flex;align-items:center;justify-content:center;background:#D9E4E0;"
                     "color:#0E4F45;font-size:38px!important;font-weight:bold}"
                     ".side h3{margin:20px 0 6px;color:#9FD8CA;border-bottom:1px solid #2F7A6C;padding-bottom:3px}"
                     ".side .ln{overflow-wrap:anywhere;margin-bottom:5px}.side ul{padding-left:16px}"
                     "h1{font-size:28px!important}.role{margin-top:4px;color:#0E6B5C;font-weight:bold;font-size:14px!important}"
                     "h2{margin:20px 0 6px;color:#0E6B5C;border-bottom:1.5px solid #0E6B5C;padding-bottom:3px}",
}


def render_resume_html(parsed, template=DEFAULT_TEMPLATE, photo=None):
    """Full HTML page for the resume. `photo` is {"content_type", "data"} or None."""
    if template not in TEMPLATES:
        raise ValueError("unknown template")
    parsed = profile_edit.with_contact(parsed)
    name, role = _name_and_role(parsed)
    contact = parsed["contact"]
    sections = _sections(parsed)
    ct = _contact_lines(contact)
    role_html = "<div class='role'>%s</div>" % _e(role) if role else ""
    ct_html = "<div class='ct'>%s</div>" % "<br>".join(_e(x) for x in ct) if ct else ""

    def main_block(allowed=None, skip=()):
        return "".join(_section_html(k, *sections[k]) for k in _ordered_keys(sections, allowed, skip))

    if template in ("classic", "modern"):
        body = "<h1>%s</h1>%s%s%s" % (_e(name), role_html if template == "modern" else "", ct_html, main_block())
    elif template == "compact":
        left = "".join(_section_html(k, *sections[k]) for k in ("skills",) if k in sections)
        right = "".join(_section_html(k, *sections[k]) for k in ("education", "certifications") if k in sections)
        rest = main_block(skip=("skills", "education", "certifications"))
        extra = "<div class='cols'><div>%s</div><div>%s</div></div>" % (left, right) if (left or right) else ""
        body = "<div><h1>%s</h1>%s</div>%s%s%s" % (
            _e(name), "<span class='role'>%s</span>" % _e(role) if role else "",
            "<div class='ct'>%s</div>" % _e(" | ".join(ct)) if ct else "", rest, extra)
    elif template == "photo_header":
        body = "<div class='head'><div><h1>%s</h1>%s%s</div>%s</div>%s" % (
            _e(name), role_html, ct_html, _photo_html(photo, name, "ph"), main_block())
    else:  # photo_sidebar
        side = _photo_html(photo, name, "ph")
        if ct:
            side += "<h3>CONTACT</h3>" + "".join("<div class='ln'>%s</div>" % _e(x) for x in (
                [contact.get("location"), contact.get("email"), contact.get("phone")] + list(contact.get("links", []))) if x)
        side += "".join(_section_html(k, *sections[k], tag="h3") for k in _ordered_keys(sections, SIDEBAR_KEYS))
        # Page text order for scanners: name and role, then contact (in the side bar), then the
        # rest. CSS places the side bar on the left with absolute positioning.
        body = ("<div class='main top'><h1>%s</h1>%s</div><div class='side'>%s</div>"
                "<div class='main rest'>%s</div>") % (_e(name), role_html, side, main_block(skip=SIDEBAR_KEYS))

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>%s</title><style>%s%s</style></head><body><div class='page'>%s</div></body></html>"
        % (_e(name), _BASE_CSS, _CSS[template], body)
    )
