# 車椅子・体重・速度の違いを補正する案（比を使う方法を中心に）

車椅子・体重・速度が違っても同じモデルで判定できるように、補正の案を整理した（2026-11-01、未実施）。これまでの検討は [補正の方法の調査](../2026-10-31/20261031_speed_weight_normalization_survey.md) と [形だけの補正](20261101_spectral_shape.md)。平坦路を基準にした補正は、基準の路面の粗さに左右されて決め手にならなかった。

## おすすめ：A・B・C の組み合わせ

どれも「比」なので、車椅子・体重・速度による揺れの大きさの違いが、分母と分子で打ち消し合う。補正のための平坦路を走る必要も無い。

### A. 局所的な基準との比（一番おすすめ）

- 各窓の揺れの強さを、**直前 30〜60 秒の静かな部分**（例：揺れの小さいほうから 20% の窓の rms）で割る。「普段の走行の何倍か」を特徴量にする。
- 基準は走行中に自動で更新されるので、基準の平坦路がばらつく問題が小さい。
- 弱点：凸凹が長く続くと基準も上がる → 基準を「静かな部分」に限る。
- 関連研究：背景の揺れのモデルとの差で路面の異常を判定（Du et al. 2020、ポットホール 96%・段差 94%）[1]。レーダーの CFAR と同じ考え方。

### B. 軸どうしの比

- 上下 ÷ 水平（z の rms ÷ 水平の大きさの rms）、上下の揺れ ÷ ピッチの角速度（ジャイロは 10.31 から記録）。
- 車椅子・体重の違いは上下にも水平にも同じように効くので、比で打ち消される。段差は前後の衝撃や傾きが大きく、凸凹は上下が主なので、路面の違いは残る。
- 関連研究：Pothole Patrol（Eriksson et al. 2008）は x と z の比、速度と z のピークの比のフィルタを使う [2][3]。

### C. 共振の周波数を基準にした帯域の比

- 普段の走行から揺れの山の周波数 f0 を推定し（汎用 15〜30 Hz、従来 30〜60 Hz。[形だけの補正](20261101_spectral_shape.md)）、帯域を「f0 の 0.5〜1 倍」「1〜2 倍」のように f0 基準で区切り、帯域どうしのパワーの比を特徴量にする。
- 体重が変わると f0 がずれる（∝ √(k/m)）が、f0 基準の帯域なら、ずれごと打ち消せる。
- 回転機械のオーダートラッキングと同じ考え方（速度の代わりに共振の周波数を基準にする）。

## 組み合わせる案

- **D. いろいろな条件を混ぜて学習 + データ拡張**：取れた条件（車椅子 2 台、体重 2 人など）は全部混ぜる。足りない条件は、振幅の 0.5〜2 倍、時間軸の伸縮（速度）、リサンプリングで周波数をずらす（体重）で補う。関連研究：LaNet（振幅のスケーリングで車種、時間の伸縮で速度の違いをまねる）[4]、TADA（時間の伸縮でドメイン汎化）[5]。
- **E. 速度による補正**（速度が分かる場合）：揺れの強さを v^γ で割る（γ はデータから求める）。SmartRoadSense（理論上 4 乗、データでもべき乗則）[6]、Nericell（速度で判定の方法を切り替える）[7]。車椅子の速さでは GPS の速度がぶれやすいのが課題。

## 優先度が低い案

- 条件を先に推定してモデルを切り替える（Iwasawa ら）：多くの条件のデータが必要。
- 分布合わせ（CORAL など）：セッションの中身で分布が変わる。
- 物理モデル（質量 + ばね）の逆算：C と考え方は同じで実装が重い。LPC より少ないパラメータで済むので、凸凹の特徴まで変えてしまう副作用は起きにくい可能性がある。

## 次にやること

1. 10.31 のデータで、A・B・C を「汎用で学習 → 従来でテスト」で試し、今の特徴量（xyz18）と比べる。
2. 11.1 の測定（55 kg・68 kg の 2 人）で、体重の違いでも同じ比較をする。
3. 効いたものに D・E を足す。

## 参考文献

[1] Du et al., "Abnormal Road Surface Recognition Based on Smartphone Acceleration Sensor," *Sensors*, 2020. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7013573/

[2] Pothole Patrol のフィルタ構成（speed、high-pass、z-peak、xz-ratio、speed vs z-ratio）の解説. https://pmc.ncbi.nlm.nih.gov/articles/PMC7583950

[3] MIT 6.S062 講義資料（Pothole Patrol）. https://6s062.github.io/6MOB/2018/materials/pothole.pdf

[4] LaNet: Real-time Lane Identification by Learning Road Surface Characteristics from Accelerometer Data. https://arxiv.org/pdf/2004.02822

[5] TADA（time warping を使ったドメイン汎化）, arXiv:2407.15174. https://arxiv.org/abs/2407.15174v2

[6] G. Alessandroni et al., "A Study on the Influence of Speed on Road Roughness Sensing: The SmartRoadSense Case," *Sensors*, 2017. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5336061/

[7] Nericell のスライド（Microsoft Research）. https://microsoft.com/en-us/research/wp-content/uploads/2016/02/ramjee-nericellkaistmar2009.pdf

（どれも概要・抜粋までの確認。本文は未確認。）
