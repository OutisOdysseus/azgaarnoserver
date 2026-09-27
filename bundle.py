#!/usr/bin/env python3
"""Bundle Azgaar's Fantasy-Map-Generator into a single self-contained HTML file.

Reads the extracted project (index.html + libs/ + modules/ + utils/ + images/ +
charges/ ...) and emits one HTML file with every JS, CSS, image and SVG inlined,
plus runtime patches so features that fetch() local files work from file://.
"""
import base64, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(HERE, "extracted")
_sub = [d for d in os.listdir(EXTRACTED) if d.startswith("Fantasy-Map-Generator")]
SRC = os.path.join(EXTRACTED, _sub[0])
OUT = os.path.join(HERE, "FMG-standalone.html")

# ---------------------------------------------------------------------------
# 1. Build data-URI map for PNG images (skip preview.png: og:image meta only)
# ---------------------------------------------------------------------------
img_dir = os.path.join(SRC, "images")
image_map = {}
for fn in sorted(os.listdir(img_dir)):
    if fn == "preview.png" or not fn.lower().endswith(".png"):
        continue
    with open(os.path.join(img_dir, fn), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    image_map[fn] = "data:image/png;base64," + b64
print(f"[images] embedded {len(image_map)} PNGs as data URIs")

def replace_images(text):
    # IMPORTANT: replace "./images/x.png" BEFORE "images/x.png" so the "./"
    # variant doesn't leave a stray leading dot.
    for fn, uri in image_map.items():
        text = text.replace("./images/" + fn, uri)
    for fn, uri in image_map.items():
        text = text.replace("images/" + fn, uri)
    return text

# ---------------------------------------------------------------------------
# 2. Build charge SVG map -> window.__CHARGES__
# ---------------------------------------------------------------------------
cdir = os.path.join(SRC, "charges")
charges = {}
for fn in sorted(os.listdir(cdir)):
    if fn.endswith(".svg"):
        with open(os.path.join(cdir, fn), "r", encoding="utf-8") as f:
            charges[fn] = f.read()
charges_json = json.dumps(charges, ensure_ascii=False)
print(f"[charges] embedded {len(charges)} SVGs ({len(charges_json)} bytes JSON)")
assert "</script" not in charges_json, "charge JSON contains </script"

# ---------------------------------------------------------------------------
# 3. Read index.html
# ---------------------------------------------------------------------------
with open(os.path.join(SRC, "index.html"), "r", encoding="utf-8") as f:
    html = f.read()
orig_len = len(html)

# Protect the commented-out umami loader so the script-inliner never touches it
UMAMI_PLACEHOLDER = "@@UMAMI_COMMENTED@@"
umami_re = re.compile(r'<!--\s*<script src="libs/umami\.js"></script>\s*-->')
assert umami_re.search(html), "commented umami line not found"
html = umami_re.sub(UMAMI_PLACEHOLDER, html)

# ---------------------------------------------------------------------------
# 4. Inline CSS  ( <link rel="stylesheet" href="X"> -> <style>...</style> )
# ---------------------------------------------------------------------------
css_count = [0]
def inline_css(m):
    path = m.group(1)
    with open(os.path.join(SRC, path), "r", encoding="utf-8") as f:
        css = f.read()
    css_count[0] += 1
    return "<style>\n" + css + "\n</style>"

html = re.sub(r'<link rel="stylesheet" href="([^"]+)">', inline_css, html)
print(f"[css] inlined {css_count[0]} stylesheets")

# ---------------------------------------------------------------------------
# 5. Per-file JS transforms (structural patches only; image swap done globally)
# ---------------------------------------------------------------------------
def transform_js(path, content):
    # (a) coa-renderer: make fetchCharge use embedded charges (window.__CHARGES__
    #     is emitted as its own <script> block before this file, so we do NOT
    #     prepend here -- that would break coa-renderer's "use strict" prologue).
    if path.endswith("modules/coa-renderer.js"):
        anchor = '    const fetched = fetch(url + charge + ".svg")'
        assert anchor in content, "fetchCharge anchor not found"
        injected = (
            '    const embedded = window.__CHARGES__ && window.__CHARGES__[charge + ".svg"];\n'
            '    if (embedded !== undefined && embedded !== null) {\n'
            '      const ehtml = document.createElement("html");\n'
            '      ehtml.innerHTML = embedded;\n'
            '      const eg = ehtml.querySelector("g");\n'
            '      if (eg) { eg.setAttribute("id", charge + "_" + id); return eg.outerHTML; }\n'
            '    }\n'
            + anchor
        )
        content = content.replace(anchor, injected, 1)

    # (b) commonUtils: getBase64 should pass through data: URIs directly
    gb_old = 'function getBase64(url, callback) {\n  const xhr = new XMLHttpRequest();'
    gb_new = ('function getBase64(url, callback) {\n'
              '  if (typeof url === "string" && url.startsWith("data:")) return callback(url);\n'
              '  const xhr = new XMLHttpRequest();')
    if path.endswith("utils/commonUtils.js"):
        assert gb_old in content, "getBase64 anchor not found"
        content = content.replace(gb_old, gb_new, 1)

    return content

# ---------------------------------------------------------------------------
# 6. Inline JS  ( <script ... src="X"></script> -> <script>...</script> )
# ---------------------------------------------------------------------------
THREE_LIBS = ["libs/three.min.js", "libs/orbitControls.min.js", "libs/objexporter.min.js"]
js_inlined = [0]
external = []
script_re = re.compile(r'<script[^>]*\bsrc="([^"]+)"[^>]*>\s*</script>')

def inline_script(m):
    src = m.group(1)
    full = m.group(0)
    if src.startswith("http"):
        external.append(src)
        return full  # keep external CDN (e.g. Dropbox SDK) untouched
    with open(os.path.join(SRC, src), "r", encoding="utf-8") as f:
        content = f.read()
    assert "</script" not in content, f"{src} contains </script"
    content = transform_js(src, content)
    js_inlined[0] += 1
    block = "<script>\n" + content + "\n</script>"
    # coa-renderer needs window.__CHARGES__ defined first. Emit it in its own
    # <script> so coa-renderer's own "use strict"; directive stays first.
    if src == "modules/coa-renderer.js":
        block = ("<script>\nwindow.__CHARGES__ = " + charges_json + ";\n</script>\n" + block)
    # Inject the runtime-loaded 3D libraries right before 3d.js so window.THREE,
    # THREE.OrbitControls and THREE.OBJExporter already exist (loadTHREE no-ops).
    if src == "modules/ui/3d.js":
        pre = ""
        for lib in THREE_LIBS:
            with open(os.path.join(SRC, lib), "r", encoding="utf-8") as lf:
                libc = lf.read()
            assert "</script" not in libc, f"{lib} contains </script"
            pre += "<script>\n" + libc + "\n</script>\n"
        return pre + block
    return block

html = script_re.sub(inline_script, html)
print(f"[js] inlined {js_inlined[0]} scripts (+3 THREE libs); external kept: {external}")

# ---------------------------------------------------------------------------
# 7. Global image -> data-URI swap across the whole document
# ---------------------------------------------------------------------------
html = replace_images(html)

# ---------------------------------------------------------------------------
# 8. Restore commented umami line and write output
# ---------------------------------------------------------------------------
html = html.replace(UMAMI_PLACEHOLDER, '<!-- <script src="libs/umami.js"></script> -->')

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print(f"[done] {orig_len} -> {len(html)} bytes written to {os.path.relpath(OUT, HERE)}")
