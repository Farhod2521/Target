# Fonts inlined into components

Four presets, one folder each, one weight per preset. Every font is under
the SIL Open Font License 1.1 (its `OFL.txt` sits next to it) and has no
Reserved Font Name, so a cut-down copy may be shipped as it is.

| Preset | Font | Weight |
|---|---|---|
| `bold` | Montserrat | 800 |
| `modern` | Inter (display optical size) | 800 |
| `elegant` | Noto Serif | 700 |
| `friendly` | Nunito | 800 |

Cut down to the letters a montage writes: Basic Latin, the Uzbek okina and
apostrophe (U+02BB, U+02BC), Russian and Uzbek Cyrillic, and common
punctuation. 13–15 KB a file.

Small on purpose: Shotstack refuses an edit over 390 KB, and every HTML5
clip carries its own copy of the font - cut again, as the clip is built,
to the letters that clip writes (`videokit.typefaces.font_css`), 2–4 KB. A font that lacks one of the Uzbek
letters is not a candidate - `tests/packages/test_videokit_fonts.py` reads
each file's character map. Manrope (no ʻ ʼ), Playfair Display (no Ҳ ҳ) and
Lora (Reserved Font Name) were tried and left out.

Made from the variable files in github.com/google/fonts with fonttools:

```bash
U="U+0020-007E,U+00A0,U+00AB,U+00BB,U+00B7,U+00D7,U+02BB,U+02BC,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2026,U+2116,U+2212,U+2022,U+20BD,U+0401,U+0410-044F,U+0451,U+040E,U+045E,U+049A,U+049B,U+0492,U+0493,U+04B2,U+04B3"
uv run fonttools varLib.instancer 'Montserrat[wght].ttf' wght=800 -o /tmp/bold.ttf
uv run pyftsubset /tmp/bold.ttf --unicodes="$U" --flavor=woff2 \
  --layout-features='kern,liga,calt' --output-file=bold/font.woff2
```

Inter takes `opsz=32 wght=800`, Noto Serif `wght=700 wdth=100`.

**A letter outside the subset** is not lost: every component writes in
`font-family: 'Brand', system-ui, sans-serif`, so the browser draws that
one letter in the system font (Shotstack renders in Chromium) - in a
different face, which is visible beside the brand's letters. Only a
letter the system font lacks too comes out as an empty box. The subset
covers what a montage writes (`tests/packages/test_videokit_fonts.py`
lists it); an emoji, for one, falls back.

**`svg/Inter-Regular.ttf`** is not inlined anywhere. It is the font text
inside an SVG logo is drawn with when the machine lacks the one the SVG
names - resvg reads only TTF/OTF, and a server with DejaVu alone would
otherwise draw a text-only logo as nothing at all. Inter 400, Latin,
Latin Extended-A, Cyrillic and the Uzbek okina and apostrophe; 57 KB.
