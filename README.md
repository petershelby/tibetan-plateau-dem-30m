# Tibetan Plateau DEM 30 m (Copernicus GLO-30)

Copernicus GLO-30 mosaic for **75–105°E, 25–41°N**, built from the 480
one-degree COG tiles in the AWS Open Data bucket `copernicus-dem-30m`.

## Download

See the [v1 release](https://github.com/petershelby/tibetan-plateau-dem-30m/releases/tag/v1).
The 30 m BigTIFF is split into <2 GB parts; concatenate `part_aa`, `part_ab`,
`part_ac` in order, then verify with `SHA256SUMS.txt`.

## Product

| Item | Value |
|---|---|
| Native extent | 74.9998611°E–104.9998611°E, 25.0001389°N–41.0001389°N |
| Requested extent | 75–105°E, 25–41°N |
| Grid | 108,000 × 57,600 pixels, 1 arc-second |
| CRS | EPSG:4326 |
| Vertical datum | EGM2008 orthometric metres |
| Data type | Int16 metres, nodata −9999 |
| 30 m file | 4.87 GB BigTIFF, DEFLATE predictor 2 |
| 90 m file | 743 MB, 3×3 average |

The native Copernicus grid has pixel centres on integer arc-seconds, so the
tile mosaic is offset from the nominal degree boundary by half a pixel
(≈14 m).  This is the source grid, not a processing shift.

## Build

The GitHub Actions workflow downloads each tile, converts it to Int16
DEFLATE and deletes the Float32 original, then mosaics the converted tiles
and publishes the release.  See [`scripts/build.py`](scripts/build.py).

## Attribution

Contains modified Copernicus DEM data:

> produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and
> © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the
> European Union and ESA; all rights reserved.

> The organisations in charge of the Copernicus programme by law or by
> delegation do not incur any liability for any use of the Copernicus
> WorldDEM-30.
