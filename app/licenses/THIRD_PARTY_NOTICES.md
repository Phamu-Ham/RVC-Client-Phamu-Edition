# 第三者ソフトウェアの表示（公開前・確認中）

本書は第三者の許諾を変更するものではありません。コード、モデル、ネイティブライブラリごとに、その原文を優先します。Phamu Studioの追加・改変コードはMITに確定しましたが、第三者部品を含めた結合配布物の確認は継続中です。

## 収集済み文書

- RVC: `rvc/LICENSE`。Retrieval-based-Voice-Conversion-WebUIのMIT Licenseを保持します。
- Phamu Studioの追加・改変コード: `phamu/LICENSE`。MIT Licenseを採用し、読めるソースとともに提供します。元RVCの表示を削除・置換しません。
- Python: `python/LICENSE.txt`。実際に使用中のPython 3.9.13環境の原文です。
- Tcl/Tk: `tcl-tk/`。実行環境に含まれるlicense.termsを保持します。
- その他: `dependencies.json`に実際の67パッケージのバージョン、元パッケージのライセンス表記、原文の場所を記載しています。未知・空欄のメタデータを推測でMITに置換していません。
- 同名のLICENSEが複数ある場合も、パッケージ内の相対位置を保ち、取りこぼさず収録します。

## 個別補足

### PySimpleGUI 4.60.4

実際の`PySimpleGUI.py`冒頭にはLGPL3+の指定があります。現行最新版の利用条件ではなく、この使用版の条件を対象にします。原ソース冒頭150行を含む著作権・注意事項・コメントを保持し、利用者向け「使い方.txt」に利用を表示します。

不足していた標準ライセンス全文は`supplemental/LGPL-3.0.txt`と`supplemental/GPL-3.0.txt`に収録しています。原ソースは最終候補でも難読化せず同梱します。

### praat-parselmouth 0.4.2 / Praat

GPLv3。公式ソースの版は0.4.2です。ライセンス本文と元の著作権表示を保持します。対応ソース・ビルドに必要なファイルの提供、および結合配布物の条件の確認が必要です。ソースを取得したことだけで適合完了とは扱いません。

公式: https://github.com/YannickJadoul/Parselmouth/tree/v0.4.2

### SoundFile 0.11.0 / libsndfile 1.1.0

Python側のSoundFileはBSD、同梱DLLのlibsndfileはLGPLです。`soundfile/`に原文を含めています。libsndfileの対応ソースとバイナリのビルド由来は確認中です。

### ANTLR 4.8 / FlatBuffers 23.5.9

インストール済み配布物に本文がないため、同じバージョンの公式リポジトリから補いました。

- ANTLR: `supplemental/antlr4-4.8-LICENSE.txt`（BSD 3-Clause）
- FlatBuffers: `supplemental/flatbuffers-23.5.9-LICENSE.txt`（Apache-2.0）

### PyTorch 2.0.0+cu118 / CUDA 11.8 / cuDNN 8.7

PyTorchの原LICENSE・NOTICEは`torch/`に保持します。CUDA/cuDNNのバイナリはPyTorchコードのBSDライセンスだけで扱えるものではありません。再配布可能ファイル、追加条件、GPL部品との結合条件は確認中です。

公式条件:
- https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html
- https://docs.nvidia.com/deeplearning/cudnn/archives/cudnn-870/sla/index.html

### HuBERT / RMVPE

`lj1995/VoiceConversionWebUI`の配布元はMITと表示しています。実際の3ファイルのSHA-256が公開LFSハッシュと一致することを確認しました。原モデル側の許諾とミラー側の表示の関係は継続確認事項です。

- HuBERT元プロジェクト: https://github.com/facebookresearch/fairseq/tree/main/examples/hubert
- FacebookのHuBERT Base公開カード（Apache-2.0表示）: https://huggingface.co/facebook/hubert-base-ls960
- RMVPE元プロジェクト: https://github.com/Dream-High/RMVPE
- `supplemental/RMVPE-Apache-2.0.txt`に原プロジェクトの文書も収録します。

## モデル商品との区別

別途入手する音声モデル・Index・個人画像はこのライブラリ一覧の対象外です。各配布元の条件に従ってください。クライアントのライセンスを決めることによって、別売りモデルの利用規約を変更することはありません。
