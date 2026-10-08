#!/usr/bin/env python3
"""Render a Deckset lecture as a Marp deck.

The lectures stay Deckset source; this writes a Marp copy to
.build/marp/<name>.md and, with --html or --pdf, runs marp-cli on it.
With --site DIR it renders every deck given into DIR in one marp-cli run,
PDF and HTML, and copies the figures the HTML decks load to DIR/media.

    python3 py/marp.py lectures/lr0_noise.md --html --pdf
    make marp        # the Makefile's lectures into docs/assets/marp

What changes on the way:

    header lines (footer:, slidenumbers:, ...)   YAML front matter
    <!--pan_doc: ... -->                         speaker notes (press p)
    <!--pan_latex: ... -->, pan_title/author     dropped
    <!--pan_skip: -->                            marker dropped, slide kept
    #[fit] Heading                               a section slide
    ![left fit](x) / ![right fit](x)             ![bg left contain](x)
    ![fit](x) alone on a slide                   ![bg contain](x)
    ![fit](x) next to text, ![inline ...](x)     an image in the flow
    [.column]                                    a CSS grid column
    [.background-color: c]                       <!-- _backgroundColor: c -->
    figure.pdf                                   figure.svg, made if missing

The look is slides/marp/aic.css.
"""

import os
import re
import shutil
import subprocess
import sys

import click

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".build", "marp")
THEME = os.path.join(ROOT, "slides", "marp", "aic.css")

HEADER_RE = re.compile(r"^(footer|slidenumbers|autoscale|theme|text|header"
                       r"|date|build-lists|slide-transition)\s*:(.*)$")
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
PAN_RE = re.compile(r"<!--\s*pan_([a-z]+)\s*:(.*)$")
FIT_RE = re.compile(r"^(#+)\s*\[fit\]\s*(.*)$")
BG_RE = re.compile(r"^\[\.background-color:\s*([^\]]+)\]\s*$")
TEXT_RE = re.compile(r"^\[\.text:\s*(#[0-9A-Fa-f]{3,8})[^\]]*\]\s*$")
DIRECTIVE_RE = re.compile(r"^\[\.[a-z-]+[^\]]*\]\s*$")


def svg_for(path, src_dir):
    """Browsers cannot show a PDF in an <img>. Use the SVG twin the tikz
    build already makes, or convert one."""
    if not path.endswith(".pdf"):
        return path
    abs_pdf = os.path.normpath(os.path.join(src_dir, path))
    abs_svg = abs_pdf[:-4] + ".svg"
    if not os.path.isfile(abs_svg) and os.path.isfile(abs_pdf):
        subprocess.run(["pdftocairo", "-svg", abs_pdf, abs_svg], check=True)
    return path[:-4] + ".svg"


def split_header(lines):
    meta = {}
    i = 0
    while i < len(lines):
        m = HEADER_RE.match(lines[i].strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
        elif lines[i].strip():
            break
        i += 1
    return meta, lines[i:]


def strip_pan(lines):
    """Turn pan_doc blocks into plain comments (Marp's speaker notes) and
    drop everything else that only the book needs."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = PAN_RE.match(line.strip())
        if not m:
            out.append(line)
            i += 1
            continue
        kind, rest = m.group(1), m.group(2)
        # collect the whole comment
        block = [rest]
        if "-->" not in rest:
            i += 1
            while i < len(lines) and "-->" not in lines[i]:
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
        i += 1
        text = "\n".join(block)
        text = text[: text.rfind("-->")] if "-->" in text else text
        if kind == "doc" and text.strip():
            # a note may not contain "-->", nor start a directive
            text = text.replace("--", "–").strip()
            out.append("<!--\n" + text + "\n-->")
    return out


INLINE_MATH_RE = re.compile(r"\$\$(.+?)\$\$")


def fix_math(lines):
    """Deckset writes all maths as $$...$$ and decides by context: next to
    text it is inline, on its own it is a display block. Marp wants $...$
    inline, and a display block whose $$ fences start their own lines.
    Speaker notes and code fences are left alone."""
    out, display, fence, note = [], False, False, False
    for line in lines:
        s = line.strip()
        if note or fence or (not display and s.startswith("<!--")):
            if s.startswith("```"):
                fence = not fence
            elif s.startswith("<!--") and not fence:
                note = "-->" not in s
            elif note and "-->" in s:
                note = False
            out.append(line)
            continue
        if s.startswith("```"):
            fence = True
            out.append(line)
            continue
        if not display:
            whole = INLINE_MATH_RE.fullmatch(s)
            if not whole:
                line = INLINE_MATH_RE.sub(
                    lambda m: "$" + m.group(1).strip() + "$", line)
        if line.count("$$") % 2 == 0:
            out.append(line)
            continue
        # a lone fence: give it a line of its own
        pre, post = line.split("$$", 1)
        if pre.strip():
            out += [pre.rstrip(), ""] if not display else [pre.rstrip()]
        out.append("$$")
        display = not display
        if post.strip():
            out += [post.strip()] if display else ["", post.strip()]
    return out


def slides_of(lines):
    cur, out = [], []
    for line in lines:
        if line.strip() == "---":
            out.append(cur)
            cur = []
        else:
            cur.append(line)
    out.append(cur)
    return [s for s in out if any(l.strip() for l in s)]


def is_content(line):
    s = line.strip()
    return bool(s) and not s.startswith("<!--") and not IMG_RE.fullmatch(s) \
        and not DIRECTIVE_RE.match(s)


def in_note(lines):
    """Mask of the lines that sit inside a speaker-note comment."""
    mask, inside = [], False
    for l in lines:
        s = l.strip()
        if s.startswith("<!--") and not s.endswith("-->"):
            inside = True
            mask.append(True)
            continue
        mask.append(inside or (s.startswith("<!--") and s.endswith("-->")))
        if inside and s.endswith("-->"):
            inside = False
    return mask


def convert_slide(lines, src_dir, first=False, meta={}):
    notes = in_note(lines)
    visible = [l for l, n in zip(lines, notes) if not n]
    has_text = any(is_content(l) for l in visible)
    head, body, cols = [], [], []
    section = False

    def image(m):
        opts = m.group(1).split()
        path = svg_for(m.group(2), src_dir)
        side = next((o for o in opts if o in ("left", "right")), None)
        size = next((o for o in opts if o.endswith("%")), None)
        if side and has_text:
            return f"![bg {side} {size or 'contain'}]({path})"
        if "inline" in opts or has_text:
            return f"![]({path})"
        return f"![bg {size or 'contain'}]({path})"

    for line, note in zip(lines, notes):
        if note:
            body.append(line)
            continue
        s = line.strip()
        if s.startswith("<!--") and s.endswith("-->"):
            continue
        m = FIT_RE.match(s)
        if m:
            section = True
            body.append(f"{m.group(1)} {m.group(2)}")
            continue
        m = BG_RE.match(s)
        if m:
            head.append(f"<!-- _backgroundColor: {m.group(1).strip()} -->")
            continue
        m = TEXT_RE.match(s)
        if m:
            head.append(f"<!-- _color: {m.group(1)} -->")
            continue
        if s == "[.column]":
            cols.append(len(body))
            continue
        if DIRECTIVE_RE.match(s):
            continue
        body.append(IMG_RE.sub(image, line))

    words = sum(len(l.split()) for l in body
                if l.strip() and not l.strip().startswith(("<", "!", "|", "$$")))
    if section:
        head.append("<!-- _class: section -->")
    elif first:
        head.append("<!-- _class: title -->")
        body.append("")
        body.append(" · ".join(x for x in (meta.get("footer"), meta.get("date"))
                                if x))
    elif words > 110:
        head.append("<!-- _class: dense -->")
    if cols:
        # everything from the first [.column] on is laid out side by side
        pre = body[:cols[0]]
        parts = [body[a:b] for a, b in zip(cols, cols[1:] + [len(body)])]
        body = pre + ['<div class="columns">'] + sum(
            (["<div>", ""] + p + ["", "</div>"] for p in parts), []) + ["</div>"]
    return "\n".join(head + [""] + body).strip() + "\n"


def convert(src):
    src_dir = os.path.dirname(os.path.abspath(src))
    lines = open(src).read().split("\n")
    meta, lines = split_header(lines)
    lines = fix_math(strip_pan(lines))
    slides = [convert_slide(s, src_dir, i == 0, meta)
              for i, s in enumerate(slides_of(lines))]
    front = ["---", "marp: true", "theme: aic", "paginate: true",
             "_paginate: false", "_footer: ''",
             "math: mathjax", "size: 16:9"]
    if meta.get("footer"):
        front.append(f"footer: '{meta['footer']}'")
    front.append("---")
    return "\n".join(front) + "\n\n" + "\n---\n\n".join(slides)


MEDIA_RE = re.compile(r"\]\(\.\./\.\./media/([^)\s]+)\)")


def marp(theme, fmt, src, out, many=False):
    """Run marp-cli on one deck, or with many=True on every deck in the
    directory src - one run, so Chrome starts once, not per deck."""
    cmd = [os.environ.get("MARP", "marp"), "--theme", theme, "--html",
           "--allow-local-files", f"--{fmt}"]
    if fmt == "pdf":
        cmd.append("--pdf-notes")
    cmd += ["-I", src, "-o", out] if many else [src, "-o", out]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


@click.command()
@click.argument("srcs", nargs=-1, required=True)
@click.option("--html", is_flag=True, help="render HTML with marp-cli")
@click.option("--pdf", is_flag=True, help="render PDF with marp-cli")
@click.option("--site", metavar="DIR",
              help="render PDF and HTML into DIR, with the figures the "
                   "HTML decks use copied to DIR/media")
def main(srcs, html, pdf, site):
    # a site build gets a clean directory of its own, at the same depth
    # as OUT, so marp-cli's --input-dir sees exactly these decks
    out_md = OUT + "-site" if site else OUT
    if site:
        shutil.rmtree(out_md, ignore_errors=True)
    os.makedirs(out_md, exist_ok=True)
    mds = []
    for src in srcs:
        name = os.path.splitext(os.path.basename(src))[0]
        md = os.path.join(out_md, name + ".md")
        # paths in the lecture are relative to lectures/; .build/marp is
        # one level deeper, so ../media becomes ../../media
        text = convert(src).replace("](../", "](../../")
        open(md, "w").write(text)
        mds.append(md)
        print(f"marp: wrote {os.path.relpath(md, ROOT)}")
    if site:
        os.makedirs(site, exist_ok=True)
        marp(THEME, "pdf", out_md, site, many=True)
        marp(THEME, "html", out_md, site, many=True)
        # an HTML deck loads its figures at view time, so they go along
        used = set()
        for md in mds:
            used.update(MEDIA_RE.findall(open(md).read()))
        for rel in sorted(used):
            src = os.path.join(ROOT, "media", rel)
            if os.path.isfile(src):
                dst = os.path.join(site, "media", rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        for md in mds:
            out = os.path.join(site, os.path.basename(md)[:-3] + ".html")
            text = open(out).read().replace("../../media/", "media/")
            open(out, "w").write(text)
        print(f"marp: {len(mds)} decks and {len(used)} figures in {site}")
        return
    for flag, fmt in ((html, "html"), (pdf, "pdf")):
        if flag:
            for md in mds:
                marp(THEME, fmt, md, md[:-3] + "." + fmt)


if __name__ == "__main__":
    sys.exit(main())
