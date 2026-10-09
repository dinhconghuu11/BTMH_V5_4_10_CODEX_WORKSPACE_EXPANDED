BTMH V5.4.10 offline payload directory

For FULL OFFLINE customer build, run PREPARE_PORTABLE_OFFLINE_WINDOWS.bat on a Windows build PC with Internet.
It prepares Python wheels, Python installer, AI models and the PostgreSQL archive.
Complete customer packaging also requires:
  vendor\postgresql\postgresql-17.11-3-windows-x64-binaries.zip
  vendor\postgresql\postgresql-17.11-3-windows-x64-binaries.zip.sha256
  vendor\mediamtx\mediamtx_v1.21.1_windows_amd64.zip
  vendor\offline-provenance.json
  vendor\licenses\<component>\LICENSE.txt and completed DISTRIBUTION_REVIEW.txt
  vendor\licenses\ffmpeg\SOURCE.txt for exact GPL binary source/build obligations

MediaMTX 1.21.1 ZIP SHA256:
faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23
FFmpeg is carried in the pinned imageio-ffmpeg Windows wheel; its binary GPL
obligations are distinct from the Python wrapper license.
See OFFLINE_DEPLOYMENT.md and the latest third-party audit. Missing artifacts or
distribution evidence must block ZIP/EXE creation; no placeholder is a full bundle.

For developer testing on a PC that already has PostgreSQL 17, V1.12.3 can copy bin/lib/share into its private runtime without touching the existing PostgreSQL service or data.
