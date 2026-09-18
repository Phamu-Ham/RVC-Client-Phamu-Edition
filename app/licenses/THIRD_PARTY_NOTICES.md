# 第三者ソフトウェアの表示

本クライアントが利用するソフトウェアのライセンスと参照先を掲載しています。各部品の著作権表示・ライセンス原文が優先されます。Phamu StudioのMIT指定は、第三者部品や学習済み重みの利用条件を変更するものではありません。

## 主なソフトウェア

以下のパスは、この`licenses/`フォルダを基準にしています。

| ソフトウェア | バージョン | ライセンス・参照先 |
|---|---|---|
| Retrieval-based-Voice-Conversion-WebUI | — | MIT。`rvc/LICENSE` |
| Phamu Studioの追加・改変コード | b1.0 | MIT。`phamu/LICENSE` |
| Python | 3.9.13 | `python/LICENSE.txt` |
| Tcl/Tk | 同梱版 | `tcl-tk/`内の`license.terms` |
| PySimpleGUI | 4.60.4 | LGPL-3.0-or-later。使用版のソース冒頭、`supplemental/LGPL-3.0.txt`、`supplemental/GPL-3.0.txt` |
| praat-parselmouth / Praat | 0.4.2 / 内包版 | ParselmouthはGPL-3.0-or-later。`praat-parselmouth/`、[公式ソースとライセンス](https://github.com/YannickJadoul/Parselmouth/tree/v0.4.2) |
| SoundFile | 0.11.0 | BSD-3-Clause。`soundfile/soundfile-0.11.0.dist-info/LICENSE` |
| libsndfile | 1.1.0 | LGPL-2.1-or-later。`soundfile/_soundfile_data/COPYING` |
| ANTLR | 4.8 | BSD-3-Clause。`supplemental/antlr4-4.8-LICENSE.txt` |
| FlatBuffers | 23.5.9 | Apache-2.0。`supplemental/flatbuffers-23.5.9-LICENSE.txt` |
| PyTorch | 2.0.0+cu118 | BSD系ライセンスと第三者表示。`torch/`内の`LICENSE`・`NOTICE` |

その他の依存パッケージは[dependencies.json](dependencies.json)に、バージョン・配布元メタデータのライセンス表記・原文の場所を記載しています。各パッケージの原文は、対応するサブフォルダに収録しています。

## GPUランタイム

GPUランタイムには、利用するPythonパッケージとは別のライセンスが適用されます。

| ランタイム | バージョン | 公式の利用条件 |
|---|---|---|
| NVIDIA CUDA | 11.8 | [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html) |
| NVIDIA cuDNN | 8.7 | [cuDNN Software License Agreement](https://docs.nvidia.com/deeplearning/cudnn/archives/cudnn-870/sla/index.html) |
| Microsoft DirectML | 1.10.1 | [Microsoft DirectML License](https://www.nuget.org/packages/Microsoft.AI.DirectML/1.10.1/License) |

## 共通モデルの配布元

- HuBERT・RMVPEの配布元: [lj1995/VoiceConversionWebUI](https://huggingface.co/lj1995/VoiceConversionWebUI)
- HuBERT元プロジェクト: [fairseq / HuBERT](https://github.com/facebookresearch/fairseq/tree/main/examples/hubert)
- RMVPE元プロジェクト: [Dream-High/RMVPE](https://github.com/Dream-High/RMVPE)。元プロジェクトのApache-2.0本文を`supplemental/RMVPE-Apache-2.0.txt`に収録しています。

## 利用者が追加するモデル・画像

別途入手する音声モデル・Index・画像には、各配布元の利用条件が適用されます。クライアントのMIT指定によって、それらの利用条件が変更されることはありません。
