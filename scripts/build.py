# -*- coding: utf-8 -*-
"""Build a Copernicus GLO-30 mosaic for 75-105E, 25-41N on a GitHub runner.

Each 1-degree source tile is downloaded, converted to Int16 DEFLATE and the
raw Float32 tile is deleted immediately, keeping peak disk use below ~10 GB.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WEST, EAST = 75, 105
SOUTH, NORTH = 25, 41
RES = 1.0 / 3600.0
NX = int(round((EAST - WEST) / RES))
NY = int(round((NORTH - SOUTH) / RES))
X0 = WEST - 0.5 * RES
X1 = X0 + NX * RES
Y1 = NORTH + 0.5 * RES
Y0 = Y1 - NY * RES

ROOT = Path.cwd()
RAW = ROOT / "work" / "raw"
CONV = ROOT / "work" / "converted"
OUT = ROOT / "work" / "output"
REL = ROOT / "release"
for d in (RAW, CONV, OUT, REL):
    d.mkdir(parents=True, exist_ok=True)

START = time.time()


def log(msg):
    print("[%6.1fs] %s" % (time.time() - START, msg), flush=True)


def tile_name(lat, lon):
    return "Copernicus_DSM_COG_10_N%02d_00_E%03d_00_DEM" % (lat, lon)


def tile_url(lat, lon):
    n = tile_name(lat, lon)
    return ("https://copernicus-dem-30m.s3.amazonaws.com/%s/%s.tif"
            % (n, n))


def valid_tiff(path):
    try:
        if path.stat().st_size < 1_000_000:
            return False
        with open(path, "rb") as fh:
            head = fh.read(4)
        return head in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM+\x00")
    except OSError:
        return False


def one_tile(lat, lon):
    n = tile_name(lat, lon)
    conv = CONV / (n + ".tif")
    if valid_tiff(conv):
        return True
    raw = RAW / (n + ".tif")
    last = ""
    for attempt in range(4):
        try:
            if raw.exists():
                raw.unlink()
            r = subprocess.run([
                "curl", "-L", "--fail", "--silent", "--show-error",
                "--retry", "3", "--retry-delay", "2",
                "--connect-timeout", "20", "--max-time", "300",
                "-o", str(raw), tile_url(lat, lon),
            ], capture_output=True, text=True, timeout=330)
            if r.returncode != 0 or not valid_tiff(raw):
                last = (r.stderr or "bad download")[:200]
                time.sleep(3)
                continue
            r = subprocess.run([
                "gdal_translate", "-q", "-of", "GTiff", "-ot", "Int16",
                "-co", "TILED=YES", "-co", "BLOCKXSIZE=512",
                "-co", "BLOCKYSIZE=512", "-co", "COMPRESS=DEFLATE",
                "-co", "PREDICTOR=2", "-co", "BIGTIFF=NO",
                str(raw), str(conv),
            ], capture_output=True, text=True, timeout=180)
            if r.returncode != 0 or not valid_tiff(conv):
                last = (r.stderr or "gdal_translate failed")[:200]
                time.sleep(3)
                continue
            return True
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:200]
            time.sleep(3)
        finally:
            if raw.exists():
                raw.unlink()
    log("FAIL %s: %s" % (n, last))
    return False


def split_file(path, chunk=1800 * 1024 * 1024):
    parts = []
    with open(path, "rb") as src:
        idx = 0
        while True:
            data = src.read(chunk)
            if not data:
                break
            suffix = chr(ord("a") + idx // 26) + chr(ord("a") + idx % 26)
            part = REL / (path.name + ".part_" + suffix)
            part.write_bytes(data)
            parts.append(part)
            idx += 1
    return parts


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    tiles = [(lat, lon) for lat in range(SOUTH, NORTH)
             for lon in range(WEST, EAST)]
    log("tiles: %d" % len(tiles))
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        for i, good in enumerate(pool.map(lambda p: one_tile(*p), tiles), 1):
            ok += bool(good)
            if i % 20 == 0 or i == len(tiles):
                log("converted %d/%d (ok=%d)" % (i, len(tiles), ok))
    if ok != len(tiles):
        raise SystemExit("only %d/%d tiles converted" % (ok, len(tiles)))

    filelist = ROOT / "work" / "tiles.txt"
    with open(filelist, "w", encoding="utf-8") as fh:
        for lat, lon in tiles:
            fh.write(str(CONV / (tile_name(lat, lon) + ".tif")) + "\n")

    vrt = ROOT / "work" / "mosaic.vrt"
    log("building VRT on native 1-arcsec grid")
    subprocess.run([
        "gdalbuildvrt", "-overwrite",
        "-te", "%.10f" % X0, "%.10f" % Y0, "%.10f" % X1, "%.10f" % Y1,
        "-tr", "%.15f" % RES, "%.15f" % RES,
        "-r", "bilinear", "-input_file_list", str(filelist), str(vrt),
    ], check=True, capture_output=True, text=True)

    final = OUT / "TibetanPlateau_DEM_30m.tif"
    log("mosaicking %dx%d -> Int16 BigTIFF" % (NX, NY))
    subprocess.run([
        "gdal_translate", "-of", "GTiff", "-ot", "Int16",
        "-a_nodata", "-9999",
        "-co", "TILED=YES", "-co", "BLOCKXSIZE=512",
        "-co", "BLOCKYSIZE=512", "-co", "COMPRESS=DEFLATE",
        "-co", "PREDICTOR=2", "-co", "BIGTIFF=YES",
        "-co", "NUM_THREADS=ALL_CPUS", str(vrt), str(final),
    ], check=True, capture_output=True, text=True)
    log("overviews")
    subprocess.run([
        "gdaladdo", "-r", "average",
        "--config", "COMPRESS_OVERVIEW", "DEFLATE",
        "--config", "BIGTIFF_OVERVIEW", "YES",
        str(final), "2", "4", "8", "16", "32", "64", "128",
    ], check=True, capture_output=True, text=True)

    tif90 = OUT / "TibetanPlateau_DEM_90m.tif"
    log("90 m overview")
    subprocess.run([
        "gdal_translate", "-of", "GTiff", "-outsize", "36000", "19200",
        "-r", "average", "-ot", "Int16", "-a_nodata", "-9999",
        "-co", "TILED=YES", "-co", "BLOCKXSIZE=512",
        "-co", "BLOCKYSIZE=512", "-co", "COMPRESS=DEFLATE",
        "-co", "PREDICTOR=2", "-co", "BIGTIFF=YES",
        "-co", "NUM_THREADS=ALL_CPUS", str(final), str(tif90),
    ], check=True, capture_output=True, text=True)
    subprocess.run(["gdaladdo", "-r", "average", str(tif90),
                    "2", "4", "8", "16"],
                   check=True, capture_output=True, text=True)

    # Statistics for the README / metadata.
    info = json.loads(subprocess.check_output(
        ["gdalinfo", "-json", "-mm", str(final)], text=True))
    band = info["bands"][0]
    meta = {
        "source": "Copernicus DEM GLO-30 (AWS Open Data)",
        "crs": "EPSG:4326",
        "vertical_datum": "EGM2008 orthometric metres",
        "resolution_arcsec": 1,
        "width": NX,
        "height": NY,
        "extent_native": [round(X0, 10), round(Y0, 10),
                          round(X1, 10), round(Y1, 10)],
        "dtype": "Int16",
        "nodata": -9999,
        "min": band.get("minimum"),
        "max": band.get("maximum"),
        "file_size": final.stat().st_size,
    }
    (OUT / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("min=%s max=%s size=%.2f GB" %
        (meta["min"], meta["max"], final.stat().st_size / 1073741824.0))

    log("splitting release assets")
    parts = split_file(final) + split_file(tif90)
    checks = []
    for p in parts:
        checks.append("%s  %s" % (sha256(p), p.name))
    checks.append("%s  %s" % (sha256(OUT / "metadata.json"),
                              "metadata.json"))
    (REL / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n",
                                        encoding="utf-8")
    shutil.copyfile(OUT / "metadata.json", REL / "metadata.json")
    readme = (
        "Tibetan Plateau Copernicus GLO-30 DEM\\n"
        "Extent (native 1 arc-second grid): %.8fE - %.8fE, "
        "%.8fN - %.8fN\\n"
        "Requested extent: 75E - 105E, 25N - 41N\\n"
        "CRS: EPSG:4326; vertical datum: EGM2008; Int16 metres; "
        "nodata -9999.\\n"
        "Source: Copernicus DEM GLO-30, AWS Open Data bucket "
        "copernicus-dem-30m.\\n"
        "Contains modified Copernicus DEM data (c) DLR e.V. 2010-2014 and "
        "(c) Airbus Defence and Space GmbH 2014-2018, provided under "
        "COPERNICUS by the European Union and ESA.\\n"
        % (X0, X1, Y0, Y1)
    )
    (REL / "README.txt").write_text(readme, encoding="utf-8")
    log("release files: %s" % ", ".join(p.name for p in parts))
    log("DONE")


if __name__ == "__main__":
    main()
