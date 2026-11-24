#!/usr/bin/env python3
"""Generate a dependency-free Android WebView project from a bot payload.

payload.json:
  mode:       "url" | "html"
  url:        website URL (mode=url)  | asset API url of ZIP/HTML (mode=html)
  appName:    application label
  iconUrl:    (optional) asset API url of icon image
Usage: gen_webapk.py payload.json OUT_DIR
"""
import json, os, re, shutil, subprocess, sys, zipfile, random, string
from xml.sax.saxutils import escape

payload = json.load(open(sys.argv[1], encoding="utf-8"))
out = sys.argv[2]
mode = payload.get("mode", "url")
app_name = (payload.get("appName") or "My App").strip()[:40] or "My App"
token = os.environ.get("GH_TOKEN", "")


def download(url, dest):
    cmd = ["curl", "-fL", "-o", dest, "-H", "Accept: application/octet-stream"]
    if "api.github.com" in url and token:
        cmd += ["-H", "Authorization: Bearer " + token]
    subprocess.check_call(cmd + [url])


slug = re.sub(r"[^a-z0-9]", "", app_name.lower()) or "app"
if not slug[0].isalpha():
    slug = "a" + slug
rand = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
package = "com.webapk.%s%s" % (slug[:12], rand)
pkg_path = package.replace(".", "/")

app = os.path.join(out, "app")
main = os.path.join(app, "src/main")
java_dir = os.path.join(main, "java", pkg_path)
res = os.path.join(main, "res")
assets = os.path.join(main, "assets")
for d in (java_dir, os.path.join(res, "values"), assets):
    os.makedirs(d, exist_ok=True)

# ---------- start url / assets ----------
if mode == "html":
    src = "/tmp/html_src"
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(src)
    dl = "/tmp/html_payload.bin"
    download(payload["url"], dl)
    if zipfile.is_zipfile(dl):
        with zipfile.ZipFile(dl) as z:
            z.extractall(src)
    else:
        shutil.copy(dl, os.path.join(src, "index.html"))
    # find the folder that contains index.html (or the only .html)
    root = None
    for dp, _, fn in os.walk(src):
        if "__MACOSX" in dp:
            continue
        if "index.html" in fn:
            if root is None or len(dp) < len(root):
                root = dp
    if root is None:
        htmls = []
        for dp, _, fn in os.walk(src):
            if "__MACOSX" in dp:
                continue
            htmls += [os.path.join(dp, f) for f in fn if f.lower().endswith((".html", ".htm"))]
        if not htmls:
            sys.exit("::error::Tidak ada file .html dalam ZIP.")
        htmls.sort(key=len)
        root = os.path.dirname(htmls[0])
        os.rename(htmls[0], os.path.join(root, "index.html"))
    www = os.path.join(assets, "www")
    shutil.copytree(root, www)
    start_url = "file:///android_asset/www/index.html"
else:
    start_url = payload["url"].strip()
    if not re.match(r"^https?://", start_url):
        start_url = "https://" + start_url

# ---------- icon ----------
icon_ok = False
icon_dir = os.path.join(res, "mipmap-xxxhdpi")
os.makedirs(icon_dir, exist_ok=True)
icon_png = os.path.join(icon_dir, "ic_launcher.png")
try:
    if payload.get("iconUrl"):
        raw = "/tmp/icon_raw"
        download(payload["iconUrl"], raw)
        subprocess.check_call(["convert", raw + "[0]", "-resize", "192x192!", "PNG32:" + icon_png])
        icon_ok = True
except Exception as e:
    print("icon gagal, pakai default:", e)
if not icon_ok:
    try:
        letter = re.sub(r"[^A-Za-z0-9]", "", app_name)[:1].upper() or "A"
        subprocess.check_call(["convert", "-size", "192x192", "xc:#2563eb", "-gravity", "center",
                               "-fill", "white", "-pointsize", "110", "-annotate", "0", letter, "PNG32:" + icon_png])
        icon_ok = True
    except Exception as e:
        print("icon default gagal:", e)
        shutil.rmtree(icon_dir, ignore_errors=True)

# ---------- gradle ----------
open(os.path.join(out, "settings.gradle"), "w").write(
    "pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\n"
    "dependencyResolutionManagement { repositories { google(); mavenCentral() } }\n"
    "rootProject.name = 'WebApp'\ninclude ':app'\n")
open(os.path.join(out, "build.gradle"), "w").write(
    "plugins { id 'com.android.application' version '8.5.2' apply false }\n")
open(os.path.join(out, "gradle.properties"), "w").write(
    "org.gradle.jvmargs=-Xmx2g\nandroid.useAndroidX=false\nandroid.nonTransitiveRClass=true\n")
open(os.path.join(app, "build.gradle"), "w").write("""plugins { id 'com.android.application' }
android {
    namespace '%s'
    compileSdk 34
    defaultConfig {
        applicationId '%s'
        minSdk 21
        targetSdk 34
        versionCode 1
        versionName '1.0'
    }
    signingConfigs {
        release {
            storeFile file('../ks.jks')
            storePassword 'android'
            keyAlias 'key'
            keyPassword 'android'
        }
    }
    buildTypes {
        release {
            minifyEnabled false
            signingConfig signingConfigs.release
        }
    }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
}
""" % (package, package))

# ---------- manifest / resources ----------
icon_attr = ' android:icon="@mipmap/ic_launcher"' if icon_ok else ""
open(os.path.join(main, "AndroidManifest.xml"), "w").write("""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
    <application
        android:label="@string/app_name"%s
        android:usesCleartextTraffic="true"
        android:allowBackup="false"
        android:hardwareAccelerated="true"
        android:theme="@android:style/Theme.Material.Light.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden|smallestScreenSize|screenLayout"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
""" % icon_attr)
open(os.path.join(res, "values/strings.xml"), "w", encoding="utf-8").write(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">%s</string>\n</resources>\n'
    % escape(app_name).replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'"))

java_start = start_url.replace("\\", "\\\\").replace('"', '\\"')
open(os.path.join(java_dir, "MainActivity.java"), "w").write("""package %s;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.view.KeyEvent;
import android.webkit.*;

public class MainActivity extends Activity {
    private static final String START_URL = "%s";
    private static final int FILE_REQ = 1001;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (u.startsWith("http://") || u.startsWith("https://") || u.startsWith("file://")) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u)));
                } catch (Exception ignored) {}
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView w, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = cb;
                try {
                    startActivityForResult(p.createIntent(), FILE_REQ);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((url, ua, cd, mime, len) -> {
            try {
                DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                req.setMimeType(mime);
                req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, URLUtil.guessFileName(url, cd, mime));
                ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(req);
            } catch (Exception ignored) {}
        });
        if (b != null) web.restoreState(b); else web.loadUrl(START_URL);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == FILE_REQ && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data));
            fileCallback = null;
        }
        super.onActivityResult(req, res, data);
    }

    @Override
    protected void onSaveInstanceState(Bundle o) {
        super.onSaveInstanceState(o);
        web.saveState(o);
    }

    @Override
    public boolean onKeyDown(int k, KeyEvent e) {
        if (k == KeyEvent.KEYCODE_BACK && web.canGoBack()) { web.goBack(); return true; }
        return super.onKeyDown(k, e);
    }
}
""" % (package, java_start))
print("OK package=%s start=%s icon=%s" % (package, start_url, icon_ok))
