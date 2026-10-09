# Third-party payload and distribution audit — 2026-10-09

This audit covers the artifacts acquired for this task. It is not a commercial release certificate. Customer installation must use the local payload; these upstream URLs are build-machine acquisition references only.

## Acquired, hash-verified artifacts

| Component | Canonical payload path | SHA256 |
|---|---|---|
| MediaMTX 1.21.1 Windows amd64 | `vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip` | `faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23` |
| Python 3.12.10 Windows amd64 installer | `vendor/python-3.12.10-amd64.exe` | `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb` |
| YuNet 2023mar | `models/face_detection_yunet_2023mar.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| SFace 2021dec | `models/face_recognition_sface_2021dec.onnx` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |
| MiniFASNetV2, yakhyo export | `models/minifasnet_v2.onnx` | `b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907` |

MediaMTX bytes match the project pin and the [official release checksum file](https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/checksums.sha256). Python bytes match the [official installer SPDX record](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe.spdx.json), also observed in its official Sigstore metadata. Model hashes match the supported variants in `scripts/download_models.py` and PAD's preprocessing profile. Build acquisition details and sizes are retained in `.qa_production/artifact-acquisition.json`; primary license files are in `vendor/licenses/<component>/LICENSE.txt`. These acquisition notes are separate from completed distribution review.

The 113759-byte `.test_media` ZIP remains rejected: its SHA256 is `4b8cdf50332e0b7e9905dbbf29755e5a27c5e7f05be0fb850c81dd562aac41c1`, not the release pin. It was not executed, imported or substituted for the authentic archive.

## Primary license findings and remaining obligations

| Component | Primary-source finding | Distribution evidence required |
|---|---|---|
| MediaMTX | [MIT at v1.21.1](https://github.com/bluenviron/mediamtx/blob/v1.21.1/LICENSE) permits redistribution subject to retained license/copyright notices. | Retain the exact archive license and any third-party notices applicable to the binary; record the review in the payload. |
| Python | [Official SPDX](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe.spdx.json) labels CPython PSF-2.0 and inventories bundled libraries. [CPython 3.12.10 LICENSE](https://github.com/python/cpython/blob/v3.12.10/LICENSE) was acquired. | Retain installer/license notices and review bundled-library notices; upstream SPDX uses NOASSERTION for several subcomponents and is not a complete legal conclusion. |
| YuNet | [Per-model MIT license](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE). | Retain the Shiqi Yu copyright and permission notice with the unmodified pinned model. |
| SFace | [Model directory](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) explicitly assigns Apache-2.0 to its files. | Retain the per-model license and applicable attribution/NOTICE material; model license is distinct from the OpenCV runtime wheel license. |
| MiniFASNetV2 | [yakhyo model export repository](https://github.com/yakhyo/face-anti-spoofing) is Apache-2.0 and identifies [Minivision](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) as upstream, also with an Apache-2.0 license. | Review the exact export/weight lineage and retain both applicable upstream notices; a repository badge alone is not a completed payload review. |
| imageio-ffmpeg wrapper | [v0.6.0 LICENSE](https://github.com/imageio/imageio-ffmpeg/blob/v0.6.0/LICENSE) is BSD-2-Clause. | Retain wrapper notice; this license does not cover all bundled FFmpeg binary obligations. |
| FFmpeg binary in that wheel | Actual `ffmpeg -version`: **7.1-essentials_build-www.gyan.dev**, configured with `--enable-gpl --enable-version3 --enable-static`, including libx264/libx265. [FFmpeg's primary license guidance](https://ffmpeg.org/legal.html) explains that optional GPL components change the binary's applicable license. | Exact corresponding source, build/configuration and GPL/third-party notices for this binary remain a distribution blocker. Do not label the entire wheel payload BSD-only or create a placeholder SOURCE.txt claiming compliance. |
| PostgreSQL/EDB archive | Expected `vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip`; [EDB lists 17.11 binaries](https://www.enterprisedb.com/download-postgresql-binaries). [PostgreSQL core license](https://www.postgresql.org/about/licence/) permits redistribution with notices. | Exact archive not acquired/verified here. Upstream digest/provenance and bundled third-party notices are missing. No guessed checksum or self-generated sidecar is represented as independently verified vendor evidence. |
| Python wheels | 60 Windows/portable wheels were resolved/downloaded from official PyPI for the unchanged runtime/media requirements. | Full per-wheel hashes/notices and transitive closure are recorded by the offline audit; binary subcomponents may add obligations beyond wheel metadata. |

## Fresh execution evidence

- Authentic MediaMTX ZIP: official offline importer PASS into `.qa_production/media-runtime`; supported resolver PASS; actual `mediamtx.exe --version` returned `v1.21.1`.
- Existing Python 3.12.10 created `.qa_production/offline-venv`; all 60 wheels installed with `--no-index --find-links vendor/wheels`. `pip check` returned no broken requirements. This does not test the downloaded Python EXE on a clean Windows host.
- Exact acquired YuNet/SFace loaded through the existing FaceCore; PAD passed its real ONNX Runtime load/probe with `yakhyo_live1_raw255`; FFmpeg resolved locally. Evidence: `.qa_production/model-runtime-results.json`.
- No camera connection, decoded browser WebRTC, person/spoof accuracy, GPU load, PostgreSQL service, phone capture or clean-machine installation is certified by these tests.

QA helpers, virtual environments, test databases/keys and acquisition scratch files under `.qa_production` are excluded from release packaging. Complete offline audit must continue to fail closed while mandatory artifacts or distribution evidence are missing.

## Final payload gate

The fresh [payload audit](OFFLINE_PAYLOAD_AUDIT_20261009.json) resolved all 60 wheels offline and verified the five present artifact pins. It returned BLOCKED with fourteen issues: PostgreSQL archive and acquisition sidecar; completed distribution review records for the six required components and PostgreSQL license; FFmpeg license/review/exact-source evidence; and wheel notices absent from `dnspython-2.9.0-py3-none-any.whl` and `flatbuffers-25.12.19-py2.py3-none-any.whl`. Wheel metadata labels alone were not substituted for retained notices. No wheel was repacked or invented notice added. The actual package command returned 2 and created no release stage or ZIP.
