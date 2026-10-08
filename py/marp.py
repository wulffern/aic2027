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


SVG_INLINE_MAX = 4_000_000


def aspect(path, src_dir):
    """Width over height of a figure, from the SVG viewBox or the PNG
    header; 1.5 when it cannot be read."""
    f = os.path.normpath(os.path.join(src_dir, path))
    try:
        if f.endswith(".svg"):
            head = open(f, errors="ignore").read(3000)
            m = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', head)
            if m:
                return float(m.group(1)) / float(m.group(2))
        if f.endswith(".png"):
            b = open(f, "rb").read(24)
            return int.from_bytes(b[16:20], "big") / int.from_bytes(b[20:24], "big")
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return 1.5


def inline_svg(path, src_dir, key):
    """The SVG's own markup, to put straight into the HTML deck. An <img>
    of an SVG is decoded to a bitmap at its layout size, and Safari then
    scales that bitmap with the slide; markup in the page stays vector.
    Ids get a per-figure prefix so glyphs of two figures never collide.
    None for raster files and for SVGs too large to inline."""
    f = os.path.normpath(os.path.join(src_dir, path))
    if not f.endswith(".svg") or not os.path.isfile(f) \
            or os.path.getsize(f) > SVG_INLINE_MAX:
        return None
    t = open(f, errors="ignore").read()
    t = t[t.index("<svg"):]
    t = re.sub(r'\bid="([^"]+)"', rf'id="{key}-\1"', t)
    t = re.sub(r'((?:xlink:)?href)="#([^"]+)"', rf'\1="#{key}-\2"', t)
    t = re.sub(r"url\(#([^)]+)\)", rf"url(#{key}-\1)", t)
    t = re.sub(r'<svg([^>]*?)\swidth="[^"]*"', r"<svg\1", t, count=1)
    t = re.sub(r'<svg([^>]*?)\sheight="[^"]*"', r"<svg\1", t, count=1)
    t = t.replace("<svg", '<svg class="figsvg" preserveAspectRatio="xMidYMid meet"', 1)
    #- an HTML block ends at a blank line
    return "\n".join(l for l in t.split("\n") if l.strip())


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


FIG_RE = re.compile(r"@@FIG(\d+)@@")


def convert_slide(lines, src_dir, first=False, meta={}, svg=False, keyp="f"):
    notes = in_note(lines)
    head, body, cols, classes = [], [], [], []
    figs = []
    section = False

    def image(m):
        opts = m.group(1).split()
        path = svg_for(m.group(2), src_dir)
        side = next((o for o in opts if o in ("left", "right")), None)
        figs.append((path, side))
        return f"@@FIG{len(figs) - 1}@@"

    def fig_html(i):
        path = figs[i][0]
        markup = inline_svg(path, src_dir, f"{keyp}{i}") if svg else None
        return markup or f'<img src="{path}" alt="">'

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
            # the theme colours text through variables; this class
            # switches them, or the slide's own colour never shows
            classes.append("inverted")
            continue
        if s == "[.column]":
            cols.append(len(body))
            continue
        if DIRECTIVE_RE.match(s):
            continue
        body.append(IMG_RE.sub(image, line))

    words = sum(len(l.split()) for l in body
                if l.strip() and not l.strip().startswith(("<", "!", "|", "$$")))
    # lines of display maths: a long derivation needs smaller type
    maths, blocks, inside = 0, 0, False
    for l in body:
        n = l.count("$$")
        if inside or n:
            maths += 1
        if n and not inside:
            blocks += 1
        if n % 2:
            inside = not inside
    # a title and a figure, nothing else: the figure is the slide, and
    # the title shrinks to a quiet label (the book keeps it as a heading)
    shown = [l.strip() for l, n in zip(lines, notes) if not n and l.strip()
             and not l.strip().startswith("<!--")
             and not DIRECTIVE_RE.match(l.strip())]
    heads = [l for l in shown if l.startswith("#") and not FIT_RE.match(l)]
    figure = (len(heads) == 1 and len(shown) > 1
              and all(IMG_RE.fullmatch(l) for l in shown if l not in heads))
    # a title and nothing else on the slide (the words are in the notes):
    # it is a divider, so it looks like one
    if len(heads) == 1 and len(shown) == 1 and not first:
        section = True
    if section:
        classes.append("section")
    elif first:
        classes.append("title")
        body.append("")
        body.append(" · ".join(x for x in (meta.get("footer"), meta.get("date"))
                                if x))
    elif figure or (figs and not cols and not any(
            is_content(l) and not FIG_RE.fullmatch(l.strip())
            and not l.strip().startswith("#")
            for l, n in zip(body, in_note(body)) if not n)):
        classes.append("figure")
    elif words > 70:
        classes.append("dense")
    rows = sum(1 for l in body if l.strip().startswith("|")
               and not set(l.strip()) <= set("|:- "))
    if maths > 10 and not section:
        classes.append("mathxdense")
    elif (blocks >= 6 or blocks + rows / 2 >= 5) and not section:
        classes.append("mathdense")
    if classes:
        # Marp keeps only the last _class, so give it all of them at once
        head.append(f"<!-- _class: {' '.join(classes)} -->")
    body = layout_figures(body, figs, fig_html, cols, figure or (
        figs and not any(l.strip() and not FIT_RE.match(l.strip())
                         and not l.strip().startswith(("#", "<!--"))
                         and not FIG_RE.fullmatch(l.strip())
                         for l, n in zip(body, in_note(body)) if not n)), src_dir)
    if cols:
        # everything from the first [.column] on is laid out side by side
        pre = body[:cols[0]]
        parts = [body[a:b] for a, b in zip(cols, cols[1:] + [len(body)])]
        body = pre + ['<div class="columns">'] + sum(
            (["<div>", ""] + p + ["", "</div>"] for p in parts), []) + ["</div>"]
    return "\n".join(head + [""] + body).strip() + "\n"


def layout_figures(body, figs, fig_html, cols, only_figures, src_dir):
    """Put the figures where they get the most room.

    Only figures (and a title): a row of figures filling the slide.
    Figures in columns: each where it stands. A figure with text: beside
    the text, on the side Deckset asked for, taking three fifths of the
    width - unless it is much wider than tall, then below the text at
    full width."""
    if not figs:
        return body
    box = lambda i: f'<div class="fig">{fig_html(i)}</div>'
    if cols:
        return [FIG_RE.sub(lambda m: box(int(m.group(1))), l) for l in body]
    rest = [l for l in body if not FIG_RE.fullmatch(l.strip())]
    if only_figures:
        heads = [l for l in rest if l.strip().startswith("#")]
        other = [l for l in rest if not l.strip().startswith("#")]
        return heads + ['<div class="figrow">'] + \
            [box(i) for i in range(len(figs))] + ["</div>", ""] + other
    side = figs[0][1]
    #- is the text only display maths? Equations shrink to fit a narrow
    #- column, so then the figure goes below them, not beside
    shown, inside, prose = [l for l, n in zip(rest, in_note(rest)) if not n], False, False
    for l in shown:
        t = l.strip()
        n = t.count("$$")
        if t and not inside and not n and not t.startswith(("#", "<!--", "<sub>")):
            prose = True
        if n % 2:
            inside = not inside
    if not side and (not prose or aspect(figs[0][0], src_dir) >= 1.8):
        #- wide: in its place, growing into what the text leaves
        return [FIG_RE.sub(lambda m: box(int(m.group(1))), l) for l in body]
    side = side or "right"
    heads = [l for l in rest if l.strip().startswith("#")]
    text = [l for l in rest if not l.strip().startswith("#")]
    figcell = ['<div class="side-fig">'] + \
        [box(i) for i in range(len(figs))] + ["</div>"]
    textcell = ['<div class="side-text">', ""] + text + ["", "</div>"]
    cells = figcell + textcell if side == "left" else textcell + figcell
    return heads + [f'<div class="figside {side}">'] + cells + ["</div>"]


def convert(src, svg=False):
    src_dir = os.path.dirname(os.path.abspath(src))
    lines = open(src).read().split("\n")
    meta, lines = split_header(lines)
    lines = fix_math(strip_pan(lines))
    slides = [convert_slide(s, src_dir, i == 0, meta, svg, f"s{i}f")
              for i, s in enumerate(slides_of(lines))]
    front = ["---", "marp: true", "theme: aic", "paginate: true",
             "_paginate: false", "_footer: ''",
             "math: mathjax", "size: 16:9"]
    if meta.get("footer"):
        front.append(f"footer: '{meta['footer']}'")
    front.append("---")
    return "\n".join(front) + "\n\n" + "\n---\n\n".join(slides)


MEDIA_RE = re.compile(r"(?:\]\(|src=\")\.\./\.\./media/([^)\s\"]+)")


def marp(theme, fmt, src, out, many=False):
    """Run marp-cli on one deck, or with many=True on every deck in the
    directory src - one run, so Chrome starts once, not per deck."""
    cmd = [os.environ.get("MARP", "marp"), "--theme", theme, "--html",
           "--allow-local-files", f"--{fmt}"]
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
    #- two flavours of each deck: <img> figures for the PDF, where Chrome
    #- draws them sharp, and inline SVG for the HTML deck, for Safari
    out_md = OUT + "-site" if site else OUT
    out_html = OUT + "-site-html" if site else OUT
    if site:
        shutil.rmtree(out_md, ignore_errors=True)
        shutil.rmtree(out_html, ignore_errors=True)
    os.makedirs(out_md, exist_ok=True)
    os.makedirs(out_html, exist_ok=True)
    mds, htmls = [], []
    for src in srcs:
        name = os.path.splitext(os.path.basename(src))[0]
        for svg, d, suffix, acc in ((False, out_md, "", mds),
                                    (True, out_html, "" if site else ".svg", htmls)):
            md = os.path.join(d, name + suffix + ".md")
            # paths in the lecture are relative to lectures/; .build/marp
            # is one level deeper, so ../media becomes ../../media
            text = convert(src, svg).replace("](../", "](../../") \
                .replace('src="../', 'src="../../')
            open(md, "w").write(text)
            acc.append(md)
        print(f"marp: wrote {os.path.relpath(mds[-1], ROOT)}")
    if site:
        os.makedirs(site, exist_ok=True)
        marp(THEME, "pdf", out_md, site, many=True)
        marp(THEME, "html", out_html, site, many=True)
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
    for md, h in zip(mds, htmls):
        if pdf:
            marp(THEME, "pdf", md, md[:-3] + ".pdf")
        if html:
            marp(THEME, "html", h, md[:-3] + ".html")


if __name__ == "__main__":
    sys.exit(main())
