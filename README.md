# SeestarPlanConverter

N.I.N.A.で作成したモザイク撮影用シーケンス（JSON）から、Seestar S30 Proの撮影プランを生成し、本体へ転送するWindows用GUIツールです。

N.I.N.A.で決めた各パネルの赤経・赤緯をそのまま使用し、Seestar本体の撮影プランとして登録します。プランを本体へ正常に転送できれば、撮影時にN.I.N.A.や本ツールを起動し続ける必要はありません。ただし、撮影の実行はSeestar側の状態・設定・観測条件に依存します。

## 主な機能

- LAN上のSeestarを自動検索し、接続状態を表示
- N.I.N.A.のJSONファイルから複数パネルの座標を取得
- 撮影開始時刻・各パネルの撮影時間（10分刻み）・プラン名を設定
- パネルごとの座標、開始時刻、撮影時間を一覧表示
- Seestar用プランJSONの保存
- Seestar本体への撮影プラン転送と読み戻し確認

## 動作環境

- Windows 11（開発・動作確認環境）
- Seestar S30 Pro（同一LANなど、PCから通信可能なネットワーク上にあること）
- N.I.N.A.で作成した対応形式のJSONファイル

配布用の `SeestarPlanConverter.exe` はPyInstallerの `--onefile --windowed` で作成します。EXEの実行時には通常、Pythonの別途インストールは不要です。

## 使い方

1. `SeestarPlanConverter.exe` を起動します。
2. Seestarの自動検索結果を確認します。見つからなければネットワーク接続を確認してください。
3. 「ファイル選択...」からN.I.N.A.のJSONを指定します。
4. 「開始時刻」「各パネル撮影時間」「プラン名」を設定します。
5. 撮影プラン一覧で、各パネルの赤経・赤緯と予定時刻を確認します。
6. 必要に応じて「JSONを保存」でプランをファイルに書き出します。
7. 「Seestarへ転送」を押し、送信・読み戻し結果を確認します。

> 注意：既定のN.I.N.A.ファイルパスが画面に表示される場合がありますが、パスの表示とJSONの読み込みは別の処理です。「ファイル選択...」で実際に使用するJSONを確認してください。

## 仕様・注意事項

- 本ツールは各パネルの中心座標を使用します。N.I.N.A.のパネル配置・撮影条件のすべてを再現するものではありません。
- 現行のプランは各パネルを個別ターゲットとして登録する方式です。Seestarアプリのモザイク撮影機能そのものを呼び出す方式ではありません。
- Seestarへの転送後は、プラン名、ターゲット数、座標などの読み戻し確認を行います。Seestar側で座標が小数桁に丸められることがあります。
- Seestar本体に保存したプランと、スマートフォンアプリ側で編集できるローカルプランは別扱いになる場合があります。
- 開始時刻や撮影可能時間は、現地の日付・天候・対象の高度などを考慮して設定してください。
- 本ツールの使用前に、既存のSeestar撮影プランが上書き・置換されないか確認してください。

## 開発環境からのEXE作成

プロジェクトの仮想環境（`.venv`）を有効にし、PowerShellで以下を実行します。

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SeestarPlanConverter --collect-all seestarpy NINA_to_Seestar_GUI.py
```

生成先：`dist\SeestarPlanConverter.exe`

Pythonソースファイル自体も `SeestarPlanConverter.py` に改名する場合は、上記コマンドの最後のファイル名も変更してください。

## 使用ライブラリ

- wxPython：GUI
- seestarpy：Seestarとの通信
- PyInstaller：Windows EXE化（ビルド時のみ）

## 免責

個人制作のツールです。SeestarのファームウェアやN.I.N.A.のJSON構造の変更によって動作しなくなる可能性があります。実際の観測前に撮影プランを確認してください。
