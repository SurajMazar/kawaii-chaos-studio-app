# Third-party software

Kawaii Chaos Studio is MIT-licensed (see [LICENSE](LICENSE)). It uses and, in the Mac app, ships the following.

## FFmpeg (bundled in the Mac app)

The Mac app contains an `ffmpeg` executable from the [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)
project (FFmpeg 7.1, built with libx264). That build is licensed under the **GNU General Public License v3**
(<https://www.gnu.org/licenses/gpl-3.0.html>). It is a separate program that the app runs; it is not linked into the
app. FFmpeg's source code is available at <https://ffmpeg.org/download.html> (release 7.1) and the build scripts at
<https://github.com/imageio/imageio-binaries>. If you have Homebrew's `ffmpeg` installed, the app uses that instead.

## Fonts (`fonts/`)

Baloo 2, Caveat Brush, Gaegu, Itim and Sniglet — SIL Open Font License 1.1; Permanent Marker — Apache License 2.0
(see [fonts/README.md](fonts/README.md)).

## Libraries

Python: FastAPI, Starlette, Uvicorn, python-multipart (BSD/MIT); Pillow (MIT-CMU); NumPy, SciPy (BSD); OpenCV
(Apache 2.0); boto3/botocore (Apache 2.0); argon2-cffi (MIT); cryptography (Apache 2.0/BSD); pyotp (MIT);
pywebview (BSD); PyInstaller bootloader (GPL with a bundling exception). JavaScript: React (MIT), Ant Design (MIT),
Tailwind CSS (MIT), zustand (MIT), marked (MIT), DOMPurify (Apache 2.0/MPL 2.0). Each package's own licence file is
included in its distribution.
