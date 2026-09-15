"""Shared DOCX/PPTX rendering helpers with correct RTL and pagination."""
from docx import Document
from docx.shared import Pt, Inches, RGBColor, Emu as DEmu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
try:                                    # PPTX is optional: DOCX-only runs
    from pptx import Presentation        # must not require python-pptx
    from pptx.util import Pt as PPt, Inches as PIn, Emu
    from pptx.dml.color import RGBColor as PRGB
    from pptx.enum.text import PP_ALIGN
    HAVE_PPTX = True
except ImportError:                      # pragma: no cover
    HAVE_PPTX = False

    class _Missing:
        def __init__(self, *a, **k):
            raise RuntimeError("python-pptx is not installed; DOCX output only")

    Presentation = _Missing
    PPt = PIn = Emu = lambda *a, **k: 0
    PP_ALIGN = type("PP_ALIGN", (), {"LEFT": 1, "RIGHT": 3, "CENTER": 2})

    def PRGB(*a, **k):
        return None

NAVY = RGBColor(0x14, 0x2C, 0x4A)
ACCENT = RGBColor(0xB4, 0x53, 0x09)
GREY = RGBColor(0x55, 0x5F, 0x6B)
LIGHT = RGBColor(0x8A, 0x93, 0x9E)

P_NAVY = PRGB(0x14, 0x2C, 0x4A)
P_ACCENT = PRGB(0xB4, 0x53, 0x09)
P_GREY = PRGB(0x55, 0x5F, 0x6B)
P_WHITE = PRGB(0xFF, 0xFF, 0xFF)
P_BG = PRGB(0xF6, 0xF4, 0xF0)

# --- OOXML child-order tables (elements that must follow the one we insert) ---
_AFTER_BIDI = ('w:adjustRightInd', 'w:snapToGrid', 'w:spacing', 'w:ind',
               'w:contextualSpacing', 'w:mirrorIndents', 'w:suppressOverlap',
               'w:jc', 'w:textDirection', 'w:textAlignment', 'w:textboxTightWrap',
               'w:outlineLvl', 'w:divId', 'w:cnfStyle', 'w:rPr', 'w:sectPr',
               'w:pPrChange')
_AFTER_RTL = ('w:cs', 'w:em', 'w:lang', 'w:eastAsianLayout', 'w:specVanish',
              'w:oMath', 'w:rPrChange')

# Canonical child order of w:rPr (CT_RPr). Used to insert complex-script
# properties (bCs/iCs/szCs) in a position Word will accept.
_RPR_SEQ = ('w:rStyle', 'w:rFonts', 'w:b', 'w:bCs', 'w:i', 'w:iCs', 'w:caps',
            'w:smallCaps', 'w:strike', 'w:dstrike', 'w:outline', 'w:shadow',
            'w:emboss', 'w:imprint', 'w:noProof', 'w:snapToGrid', 'w:vanish',
            'w:webHidden', 'w:color', 'w:spacing', 'w:w', 'w:kern',
            'w:position', 'w:sz', 'w:szCs', 'w:highlight', 'w:u', 'w:effect',
            'w:bdr', 'w:shd', 'w:fitText', 'w:vertAlign', 'w:rtl', 'w:cs',
            'w:em', 'w:lang', 'w:eastAsianLayout', 'w:specVanish', 'w:oMath',
            'w:rPrChange')


def _rpr_set(rPr, tag, val):
    """Set a w:rPr child in its schema-correct position."""
    existing = rPr.find(qn(tag))
    if existing is not None:
        existing.set(qn('w:val'), val)
        return
    successors = _RPR_SEQ[_RPR_SEQ.index(tag) + 1:]
    rPr.insert_element_before(_el(tag, **{'w:val': val}), *successors)
_AFTER_BIDIVISUAL = ('w:tblStyleRowBandSize', 'w:tblStyleColBandSize', 'w:tblW',
                     'w:jc', 'w:tblCellSpacing', 'w:tblInd', 'w:tblBorders',
                     'w:shd', 'w:tblLayout', 'w:tblCellMar', 'w:tblLook',
                     'w:tblCaption', 'w:tblDescription', 'w:tblPrChange')
_AFTER_KEEPNEXT = ('w:keepLines', 'w:pageBreakBefore', 'w:framePr',
                   'w:widowControl', 'w:numPr') + _AFTER_BIDI


def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), v)
    return e


def _p_rtl(par):
    """Mark a paragraph right-to-left, inserting w:bidi in schema position."""
    pPr = par._p.get_or_add_pPr()
    if pPr.find(qn('w:bidi')) is None:
        pPr.insert_element_before(_el('w:bidi'), *_AFTER_BIDI)


def _r_rtl(run):
    rPr = run._r.get_or_add_rPr()
    if rPr.find(qn('w:rtl')) is None:
        rPr.insert_element_before(_el('w:rtl'), *_AFTER_RTL)


def _keep_next(par):
    pPr = par._p.get_or_add_pPr()
    if pPr.find(qn('w:keepNext')) is None:
        pPr.insert_element_before(_el('w:keepNext'), *_AFTER_KEEPNEXT)


def _shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = _el('w:shd', **{'w:val': 'clear', 'w:fill': hexcolor})
    tcPr.append(shd)


def _table_rtl(table):
    tblPr = table._tbl.tblPr
    if tblPr.find(qn('w:bidiVisual')) is None:
        tblPr.insert_element_before(_el('w:bidiVisual'), *_AFTER_BIDIVISUAL)


def _row_cant_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(_el('w:cantSplit'))


def _row_is_header(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(_el('w:tblHeader'))


class Doc:
    def __init__(self, rtl, font='Arial'):
        self.d = Document()
        self.rtl = rtl
        self.font = font
        st = self.d.styles['Normal']
        st.font.name = font
        st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn('w:cs'), font)
        if rtl:
            self._document_defaults_rtl()
        for s in self.d.sections:
            s.left_margin = s.right_margin = Inches(0.9)
            s.top_margin = s.bottom_margin = Inches(0.75)
            if rtl:
                sectPr = s._sectPr
                if sectPr.find(qn('w:bidi')) is None:
                    sectPr.append(_el('w:bidi'))

    def _document_defaults_rtl(self):
        """Make RTL the document-wide default so no paragraph can miss it."""
        styles = self.d.styles.element
        docDefaults = styles.find(qn('w:docDefaults'))
        if docDefaults is None:
            return
        pPrDefault = docDefaults.find(qn('w:pPrDefault'))
        if pPrDefault is None:
            pPrDefault = _el('w:pPrDefault')
            docDefaults.append(pPrDefault)
        pPr = pPrDefault.find(qn('w:pPr'))
        if pPr is None:
            pPr = _el('w:pPr')
            pPrDefault.append(pPr)
        pPr.insert_element_before(_el('w:bidi'), *_AFTER_BIDI)
        rPrDefault = docDefaults.find(qn('w:rPrDefault'))
        if rPrDefault is not None:
            rPr = rPrDefault.find(qn('w:rPr'))
            if rPr is None:
                rPr = _el('w:rPr')
                rPrDefault.append(rPr)
            rPr.insert_element_before(_el('w:rtl'), *_AFTER_RTL)

    # ---------------------------------------------------------------- text
    def _style_run(self, r, size, bold=False, italic=False, color=None):
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.name = self.font
        rPr = r._r.get_or_add_rPr()
        rPr.rFonts.set(qn('w:cs'), self.font)
        # Hebrew is a complex script: Word reads szCs/bCs/iCs, not sz/b/i.
        # Without these the Hebrew renders at the wrong size and weight.
        _rpr_set(rPr, 'w:szCs', str(int(size * 2)))
        _rpr_set(rPr, 'w:bCs', '1' if bold else '0')
        _rpr_set(rPr, 'w:iCs', '1' if italic else '0')
        if color is not None:
            r.font.color.rgb = color
        if self.rtl:
            _r_rtl(r)
        return r

    def _p(self, text='', size=10.5, bold=False, color=None, space_after=6,
           space_before=0, align=None, italic=False, keep_next=False):
        par = self.d.add_paragraph()
        if self.rtl:
            _p_rtl(par)
        r = par.add_run(text)
        self._style_run(r, size, bold, italic, color)
        pf = par.paragraph_format
        pf.space_after = Pt(space_after)
        pf.space_before = Pt(space_before)
        if align:
            par.alignment = align
        # No w:jc for RTL: inside a bidi paragraph w:jc is logical, so "right"
        # means the trailing (visually left) edge. Omitting it leaves the text
        # on the start edge, which bidi already puts on the right.
        if keep_next:
            _keep_next(par)
        return par

    def title_page(self, title, subtitle, meta_lines):
        for _ in range(5):
            self._p('', size=11)
        self._p(title, size=30, bold=True, color=NAVY, space_after=6,
                align=WD_ALIGN_PARAGRAPH.CENTER)
        self._p(subtitle, size=13.5, color=ACCENT, space_after=26,
                align=WD_ALIGN_PARAGRAPH.CENTER)
        for line in meta_lines:
            self._p(line, size=10, color=GREY, space_after=4,
                    align=WD_ALIGN_PARAGRAPH.CENTER)
        self.d.add_page_break()

    def h1(self, text):
        self._p(text, size=18, bold=True, color=NAVY, space_before=4,
                space_after=9, keep_next=True)

    def h2(self, text):
        self._p(text, size=12.5, bold=True, color=ACCENT, space_before=13,
                space_after=5, keep_next=True)

    def h3(self, text):
        self._p(text, size=11, bold=True, color=NAVY, space_before=9,
                space_after=3, keep_next=True)

    def body(self, text, keep_next=False):
        first = None
        for chunk in text.split('\n\n'):
            p = self._p(chunk, size=10.5, space_after=8, keep_next=keep_next)
            first = first or p
        return first

    def bullets(self, items, bold_lead=True, keep_next=False):
        for it in items:
            par = self.d.add_paragraph()
            if self.rtl:
                _p_rtl(par)
            pf = par.paragraph_format
            pf.space_after = Pt(4)
            marker = '•  '
            if isinstance(it, tuple):
                lead, rest = it
                self._style_run(par.add_run(marker + lead), 10.5, bold=bold_lead)
                self._style_run(par.add_run(rest), 10.5)
            else:
                self._style_run(par.add_run(marker + it), 10.5)
            if keep_next:
                _keep_next(par)

    def table(self, headers, rows, widths=None):
        t = self.d.add_table(rows=1, cols=len(headers))
        t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        if self.rtl:
            _table_rtl(t)
        hdr = t.rows[0]
        _row_is_header(hdr)
        _row_cant_split(hdr)
        for i, h in enumerate(headers):
            _shade(hdr.cells[i], '142C4A')
            par = hdr.cells[i].paragraphs[0]
            if self.rtl:
                _p_rtl(par)
            self._style_run(par.add_run(h), 9.5, bold=True,
                            color=RGBColor(0xFF, 0xFF, 0xFF))
        for ri, row in enumerate(rows):
            tr = t.add_row()
            _row_cant_split(tr)
            for i, val in enumerate(row):
                if ri % 2 == 1:
                    _shade(tr.cells[i], 'F2F4F7')
                par = tr.cells[i].paragraphs[0]
                if self.rtl:
                    _p_rtl(par)
                par.paragraph_format.space_after = Pt(2)
                self._style_run(par.add_run(str(val)), 9.5)
        if widths:
            for i, w in enumerate(widths):
                for row in t.rows:
                    row.cells[i].width = Inches(w)
        self._p('', size=6, space_after=4)
        return t

    def callout(self, text, label=None):
        t = self.d.add_table(rows=1, cols=1)
        t.style = 'Table Grid'
        if self.rtl:
            _table_rtl(t)
        _row_cant_split(t.rows[0])
        c = t.rows[0].cells[0]
        _shade(c, 'FBF3EA')
        par = c.paragraphs[0]
        if self.rtl:
            _p_rtl(par)
        if label:
            self._style_run(par.add_run(label + '  '), 10, bold=True, color=ACCENT)
        self._style_run(par.add_run(text), 10)
        self._p('', size=6, space_after=4)

    def image(self, path, width_in=6.4, caption=None, keep_next=False):
        par = self.d.add_paragraph()
        if self.rtl:
            _p_rtl(par)
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_before = Pt(8)
        par.paragraph_format.space_after = Pt(3)
        par.add_run().add_picture(path, width=Inches(width_in))
        _keep_next(par)
        if caption:
            cp = self._p(caption, size=8.5, color=LIGHT, space_after=12,
                         align=WD_ALIGN_PARAGRAPH.CENTER, italic=True,
                         keep_next=keep_next)
            return cp
        return par

    def page_break(self):
        self.d.add_page_break()

    def save(self, path):
        self.d.save(path)


# ---------------------------------------------------------------- PPTX helpers

W, H = PIn(13.333), PIn(7.5)


def _para_rtl(par, rtl):
    if rtl:
        par._pPr.set('rtl', '1')
        par.alignment = PP_ALIGN.RIGHT


class Deck:
    def __init__(self, rtl, font='Arial'):
        self.p = Presentation()
        self.p.slide_width, self.p.slide_height = W, H
        self.rtl = rtl
        self.font = font

    def _blank(self, bg=P_BG):
        s = self.p.slides.add_slide(self.p.slide_layouts[6])
        bgshape = s.shapes.add_shape(1, 0, 0, W, H)
        bgshape.fill.solid()
        bgshape.fill.fore_color.rgb = bg
        bgshape.line.fill.background()
        bgshape.shadow.inherit = False
        return s

    def _tb(self, s, x, y, w, h, text, size, bold=False, color=P_NAVY,
            align=None, italic=False, spacing=1.0):
        tb = s.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for i, ln in enumerate(text.split('\n')):
            par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            par.line_spacing = spacing
            r = par.add_run()
            r.text = ln
            r.font.size = PPt(size)
            r.font.bold = bold
            r.font.italic = italic
            r.font.color.rgb = color
            r.font.name = self.font
            if align is not None:
                par.alignment = align
            else:
                _para_rtl(par, self.rtl)
        return tb

    def title_slide(self, title, subtitle, meta):
        s = self._blank(P_NAVY)
        bar = s.shapes.add_shape(1, 0, PIn(3.05), W, PIn(0.045))
        bar.fill.solid(); bar.fill.fore_color.rgb = P_ACCENT
        bar.line.fill.background(); bar.shadow.inherit = False
        self._tb(s, PIn(1.0), PIn(1.85), PIn(11.3), PIn(1.1), title, 40, True,
                 P_WHITE, PP_ALIGN.CENTER)
        self._tb(s, PIn(1.0), PIn(3.3), PIn(11.3), PIn(0.6), subtitle, 17,
                 False, P_ACCENT, PP_ALIGN.CENTER)
        self._tb(s, PIn(1.0), PIn(4.2), PIn(11.3), PIn(1.4), meta, 12, False,
                 PRGB(0xC3, 0xCD, 0xD9), PP_ALIGN.CENTER, spacing=1.35)

    def section_slide(self, kicker, title):
        s = self._blank(P_NAVY)
        self._tb(s, PIn(1.1), PIn(2.7), PIn(11.1), PIn(0.5), kicker, 14, True,
                 P_ACCENT, PP_ALIGN.CENTER)
        self._tb(s, PIn(1.1), PIn(3.3), PIn(11.1), PIn(1.2), title, 32, True,
                 P_WHITE, PP_ALIGN.CENTER)

    def _header(self, s, title, kicker=None):
        x = PIn(0.85)
        self._tb(s, x, PIn(0.4), PIn(11.6), PIn(0.7), title, 26, True, P_NAVY)
        if kicker:
            self._tb(s, x, PIn(1.05), PIn(11.6), PIn(0.35), kicker, 11.5, False,
                     P_ACCENT)
        bar_x = (x + PIn(11.6) - PIn(1.5)) if self.rtl else x
        bar = s.shapes.add_shape(1, bar_x, PIn(1.52), PIn(1.5), PIn(0.035))
        bar.fill.solid(); bar.fill.fore_color.rgb = P_ACCENT
        bar.line.fill.background(); bar.shadow.inherit = False

    def bullet_slide(self, title, bullets, kicker=None, note=None, size=15):
        s = self._blank()
        self._header(s, title, kicker)
        tb = s.shapes.add_textbox(PIn(0.85), PIn(1.85), PIn(11.6), PIn(4.7))
        tf = tb.text_frame
        tf.word_wrap = True
        first = True
        for b in bullets:
            lead, rest = b if isinstance(b, tuple) else (None, b)
            par = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            par.space_after = PPt(10)
            par.line_spacing = 1.16
            r0 = par.add_run(); r0.text = '▪  '
            r0.font.size = PPt(size); r0.font.color.rgb = P_ACCENT
            r0.font.name = self.font
            if lead:
                r1 = par.add_run(); r1.text = lead
                r1.font.size = PPt(size); r1.font.bold = True
                r1.font.color.rgb = P_NAVY; r1.font.name = self.font
            r2 = par.add_run(); r2.text = rest
            r2.font.size = PPt(size); r2.font.color.rgb = P_GREY
            r2.font.name = self.font
            _para_rtl(par, self.rtl)
        if note:
            self._tb(s, PIn(0.85), PIn(6.6), PIn(11.6), PIn(0.5), note, 11.5,
                     False, P_ACCENT, italic=True)

    def image_slide(self, title, img, kicker=None, caption=None):
        """Full-bleed slide image with a compact header."""
        s = self._blank()
        self._header(s, title, kicker)
        from PIL import Image
        iw, ih = Image.open(img).size
        avail_w, avail_h = PIn(10.6), PIn(4.75)
        scale = min(avail_w / iw, avail_h / ih)
        w, h = int(iw * scale), int(ih * scale)
        x = int((W - w) / 2)
        s.shapes.add_picture(img, x, PIn(1.8), w, h)
        if caption:
            self._tb(s, PIn(0.85), PIn(6.75), PIn(11.6), PIn(0.4), caption, 10.5,
                     False, P_GREY, PP_ALIGN.CENTER, italic=True)

    def split_slide(self, title, img, bullets, kicker=None):
        """Slide image on one side, takeaway bullets on the other."""
        s = self._blank()
        self._header(s, title, kicker)
        from PIL import Image
        iw, ih = Image.open(img).size
        avail_w, avail_h = PIn(6.4), PIn(4.6)
        scale = min(avail_w / iw, avail_h / ih)
        w, h = int(iw * scale), int(ih * scale)
        img_x = PIn(0.85) if not self.rtl else int(W - PIn(0.85) - w)
        s.shapes.add_picture(img, img_x, PIn(1.85), w, h)
        tx = int(W - PIn(0.85) - PIn(4.9)) if not self.rtl else PIn(0.85)
        tb = s.shapes.add_textbox(tx, PIn(1.9), PIn(4.9), PIn(4.6))
        tf = tb.text_frame; tf.word_wrap = True
        first = True
        for b in bullets:
            lead, rest = b if isinstance(b, tuple) else (None, b)
            par = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            par.space_after = PPt(9); par.line_spacing = 1.15
            r0 = par.add_run(); r0.text = '▪  '
            r0.font.size = PPt(12.5); r0.font.color.rgb = P_ACCENT
            r0.font.name = self.font
            if lead:
                r1 = par.add_run(); r1.text = lead
                r1.font.size = PPt(12.5); r1.font.bold = True
                r1.font.color.rgb = P_NAVY; r1.font.name = self.font
            r2 = par.add_run(); r2.text = rest
            r2.font.size = PPt(12.5); r2.font.color.rgb = P_GREY
            r2.font.name = self.font
            _para_rtl(par, self.rtl)

    def cards_slide(self, title, cards, kicker=None):
        s = self._blank()
        self._header(s, title, kicker)
        n = len(cards)
        gap = PIn(0.28)
        total = PIn(11.6)
        cw = int((total - gap * (n - 1)) / n)
        order = list(reversed(cards)) if self.rtl else cards
        for i, (head, bodytxt) in enumerate(order):
            x = PIn(0.85) + i * (cw + gap)
            box = s.shapes.add_shape(1, x, PIn(1.95), cw, PIn(4.0))
            box.fill.solid(); box.fill.fore_color.rgb = P_WHITE
            box.line.color.rgb = PRGB(0xDD, 0xD8, 0xD0)
            box.line.width = PPt(1); box.shadow.inherit = False
            tab = s.shapes.add_shape(1, x, PIn(1.95), cw, PIn(0.09))
            tab.fill.solid(); tab.fill.fore_color.rgb = P_ACCENT
            tab.line.fill.background(); tab.shadow.inherit = False
            self._tb(s, x + PIn(0.22), PIn(2.25), cw - PIn(0.44), PIn(0.8),
                     head, 15, True, P_NAVY)
            self._tb(s, x + PIn(0.22), PIn(3.05), cw - PIn(0.44), PIn(2.7),
                     bodytxt, 12, False, P_GREY, spacing=1.22)

    def table_slide(self, title, headers, rows, kicker=None, col_w=None,
                    fsize=11):
        s = self._blank()
        self._header(s, title, kicker)
        nrows, ncols = len(rows) + 1, len(headers)
        left, top, width = PIn(0.85), PIn(1.9), PIn(11.6)
        height = PIn(0.4) * nrows
        gf = s.shapes.add_table(nrows, ncols, left, top, width, height)
        tbl = gf.table
        if col_w:
            tot = sum(col_w)
            for i, w in enumerate(col_w):
                tbl.columns[i].width = Emu(int(width * w / tot))
        hdrs = list(reversed(headers)) if self.rtl else headers
        for i, h in enumerate(hdrs):
            c = tbl.cell(0, i); c.text = ''
            par = c.text_frame.paragraphs[0]
            r = par.add_run(); r.text = h
            r.font.size = PPt(fsize + 1); r.font.bold = True
            r.font.color.rgb = P_WHITE; r.font.name = self.font
            _para_rtl(par, self.rtl)
            c.fill.solid(); c.fill.fore_color.rgb = P_NAVY
        for ri, row in enumerate(rows, start=1):
            vals = list(reversed(row)) if self.rtl else row
            for ci, val in enumerate(vals):
                c = tbl.cell(ri, ci); c.text = ''
                par = c.text_frame.paragraphs[0]
                r = par.add_run(); r.text = str(val)
                r.font.size = PPt(fsize); r.font.color.rgb = P_GREY
                r.font.name = self.font
                _para_rtl(par, self.rtl)
                c.fill.solid()
                c.fill.fore_color.rgb = P_WHITE if ri % 2 else PRGB(0xF2, 0xF4, 0xF7)

    def quote_slide(self, kicker, text, attrib=None):
        s = self._blank(P_NAVY)
        self._tb(s, PIn(1.3), PIn(2.1), PIn(10.7), PIn(0.4), kicker, 13, True,
                 P_ACCENT, PP_ALIGN.CENTER)
        self._tb(s, PIn(1.3), PIn(2.75), PIn(10.7), PIn(2.2), text, 24, True,
                 P_WHITE, PP_ALIGN.CENTER, spacing=1.28)
        if attrib:
            self._tb(s, PIn(1.3), PIn(5.3), PIn(10.7), PIn(0.4), attrib, 12,
                     False, PRGB(0xC3, 0xCD, 0xD9), PP_ALIGN.CENTER)

    def save(self, path):
        self.p.save(path)
