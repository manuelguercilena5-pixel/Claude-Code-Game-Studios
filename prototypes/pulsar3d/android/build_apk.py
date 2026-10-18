"""Builds an offline Android APK of PULSAR 3D without the Android SDK or Gradle.

Toolchain (paths passed through environment variables):
  AAPT2        aapt2 binary (resource compiler/linker)
  ANDROID_JAR  platform android.jar (API 30+), used to compile and link
  DX_JAR       dalvik-dx jar (Java bytecode -> classes.dex)
  THREE_DIR    an installed three@0.170.0 package (node_modules/three)
  FONTS_DIR    folder with fonts.css (Google Fonts CSS) and the downloaded .woff2 files
  SIGNER_DIR   folder whose node_modules contains apk_sign_ts
  KEY_PEM / CERT_PEM  signing key and certificate (PEM)
  ICON_SRC     square-ish PNG used to generate launcher icons (optional)

Usage: python3 build_apk.py OUT.apk [--version-code N] [--version-name X]
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(HERE)
ENV = os.environ


def run(cmd, **kw):
    print("+", " ".join(cmd[:4]), "..." if len(cmd) > 4 else "")
    subprocess.run(cmd, check=True, **kw)


def stage_web(www):
    """Copy the game and rewrite every network dependency to a bundled file."""
    os.makedirs(os.path.join(www, "assets"), exist_ok=True)
    html = open(os.path.join(GAME, "index.html"), encoding="utf-8").read()
    html = html.replace("https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js", "./lib/three.module.js")
    html = html.replace("https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/", "./lib/addons/")
    html = re.sub(r'<link rel="preconnect"[^>]*>\n', "", html)
    html = re.sub(r'<link href="https://fonts.googleapis.com[^>]*>', '<link href="fonts/fonts.css" rel="stylesheet">', html)
    assert "jsdelivr" not in html and "googleapis" not in html, "network URL left in the bundled page"
    open(os.path.join(www, "index.html"), "w", encoding="utf-8").write(html)
    shutil.copy(os.path.join(GAME, "assets", "pulsar.glb"), os.path.join(www, "assets", "pulsar.glb"))

    three = ENV["THREE_DIR"]
    lib = os.path.join(www, "lib")
    os.makedirs(os.path.join(lib, "addons", "loaders"), exist_ok=True)
    os.makedirs(os.path.join(lib, "addons", "utils"), exist_ok=True)
    shutil.copy(os.path.join(three, "build", "three.module.js"), lib)
    jsm = os.path.join(three, "examples", "jsm")
    for d in ("postprocessing", "shaders", "environments"):
        shutil.copytree(os.path.join(jsm, d), os.path.join(lib, "addons", d))
    shutil.copy(os.path.join(jsm, "loaders", "GLTFLoader.js"), os.path.join(lib, "addons", "loaders"))
    shutil.copy(os.path.join(jsm, "utils", "BufferGeometryUtils.js"), os.path.join(lib, "addons", "utils"))

    fonts_src, fonts_dst = ENV["FONTS_DIR"], os.path.join(www, "fonts")
    os.makedirs(fonts_dst, exist_ok=True)
    css = open(os.path.join(fonts_src, "fonts.css"), encoding="utf-8").read()
    def local(m):
        name = m.group(1).replace("https://fonts.gstatic.com/s/", "").replace("/", "_")
        shutil.copy(os.path.join(fonts_src, name), os.path.join(fonts_dst, name))
        return "url(" + name + ")"
    css = re.sub(r"url\((https://fonts\.gstatic\.com[^)]*)\)", local, css)
    open(os.path.join(fonts_dst, "fonts.css"), "w", encoding="utf-8").write(css)


def make_icons(res):
    src = ENV.get("ICON_SRC")
    for name, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        d = os.path.join(res, "mipmap-" + name)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "ic_launcher.png")
        if src:
            run(["convert", src, "-resize", f"{px}x{px}", out])
        else:
            run(["convert", "-size", f"{px}x{px}", "radial-gradient:#FF2E88-#05010F", out])


def build(out_apk, version_code, version_name):
    aapt2, android_jar, dx_jar = ENV["AAPT2"], ENV["ANDROID_JAR"], ENV["DX_JAR"]
    work = tempfile.mkdtemp(prefix="pulsar-apk-")
    res, assets, gen, classes = (os.path.join(work, d) for d in ("res", "assets", "gen", "classes"))
    for d in (res, gen, classes):
        os.makedirs(d)
    stage_web(os.path.join(assets, "www"))
    make_icons(res)

    flat = os.path.join(work, "res.zip")
    run([aapt2, "compile", "--dir", res, "-o", flat])
    unsigned = os.path.join(work, "unsigned.apk")
    run([aapt2, "link", "-o", unsigned, "-I", android_jar, "--manifest", os.path.join(HERE, "AndroidManifest.xml"),
         "--min-sdk-version", "24", "--target-sdk-version", "34",
         "--version-code", str(version_code), "--version-name", version_name,
         "-A", assets, "--java", gen, "--auto-add-overlay", flat])

    sources = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(HERE, "src")) for f in fs if f.endswith(".java")]
    sources += [os.path.join(dp, f) for dp, _, fs in os.walk(gen) for f in fs if f.endswith(".java")]
    run(["javac", "--release", "8", "-nowarn", "-Xlint:-options", "-classpath", android_jar, "-d", classes] + sources)
    dex_dir = os.path.join(work, "dex")
    os.makedirs(dex_dir)
    run(["java", "-cp", dx_jar, "com.android.dx.command.Main", "--dex", "--min-sdk-version=24",
         "--output=" + os.path.join(dex_dir, "classes.dex"), classes])

    # re-pack: resources.arsc must stay stored (uncompressed) for targetSdk >= 30; the signer zipaligns
    packed = os.path.join(work, "packed.apk")
    with zipfile.ZipFile(unsigned) as zin, zipfile.ZipFile(packed, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            stored = info.filename == "resources.arsc"
            zout.writestr(info.filename, data, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        zout.write(os.path.join(dex_dir, "classes.dex"), "classes.dex", zipfile.ZIP_DEFLATED)

    run(["node", os.path.join(HERE, "sign.mjs"), packed, out_apk, ENV["KEY_PEM"], ENV["CERT_PEM"]],
        env=dict(ENV, NODE_PATH=os.path.join(ENV["SIGNER_DIR"], "node_modules")), cwd=ENV["SIGNER_DIR"])
    shutil.rmtree(work)
    print("built", out_apk, os.path.getsize(out_apk), "bytes")


if __name__ == "__main__":
    args = sys.argv[1:]
    vc = int(args[args.index("--version-code") + 1]) if "--version-code" in args else 1
    vn = args[args.index("--version-name") + 1] if "--version-name" in args else "1.0"
    build(os.path.abspath(args[0]), vc, vn)
