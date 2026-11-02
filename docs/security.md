# セキュリティ点検（2026-11-02）

ここまでの構成（ラズパイ `nas-pi` から rclone で S3 `example-nas-photo-backup` へバックアップ、同じラズパイで Immich）を、リポジトリの `docs/`・`infra/`・`backup/`・`immich/` をもとに点検した結果。

**結論**: 土台はかなり堅い。足りないのは「S3 の写真を上書きで壊される穴」と、「ラズパイ・NAS を外から触れないようにする運用ルール」の 2 つ。どちらも費用はほぼかからない。

!!! note "この点検でしたこと・していないこと"
    リポジトリの内容だけを読んだ。AWS・ラズパイ・NAS・ルーターの実際の設定は確認していない。AWS の設定変更は何もしていない（変更する場合は事前に確認をとる）。

## すでにできていること

| 対象 | できていること | どこで |
|---|---|---|
| S3 | パブリックアクセスをすべてブロック、ACL 無効（`BucketOwnerEnforced`） | `infra/s3.tf` |
| S3 | 保存時の暗号化（SSE-S3）、HTTPS 以外の通信を拒否 | `infra/s3.tf` |
| S3 | `terraform destroy` でバケットを消せない（`prevent_destroy`） | `infra/s3.tf` |
| IAM | `nas-backup` は一覧とアップロードだけ。**読み出し・削除ができない** | `infra/iam.tf` |
| IAM | アクセスキーを Terraform の state に残さない。チャットやツールに見せない | [`docs/setup-aws.md`](setup-aws.md#access-key) |
| 費用 | キーが漏れて大量にアップロードされても、予算超過で書き込みを自動停止 | `infra/budget.tf` |
| 費用 | 普段と違う課金を毎日メールで通知 | `infra/budget.tf` |
| 秘密情報 | `rclone.conf`・`.env`・`terraform.tfvars`・state は Git に入れない | `.gitignore` |
| NAS | ラズパイ専用ユーザー `nas-pi`。`Photo` は NAS 側とマウントの両方で読み取り専用 | [`docs/setup-backup.md`](setup-backup.md#nas-mount) |
| GitHub | ラズパイは読み取り専用のデプロイキーで clone | [`docs/setup-backup.md`](setup-backup.md#nas-mount) |
| Immich | 元写真は `:ro` でマウント。Immich から消せない | `immich/docker-compose.yml` |
| Immich | DB（PostgreSQL）と Redis はポートを公開していない | `immich/docker-compose.yml` |
| Immich | ルーターのポートは開けず、外からは Tailscale だけ | [`docs/spec.md` 8章](spec.md#immich) |

ランサムウェアで PC から NAS の写真が暗号化された場合も、S3 側は守られる。`--immutable` で上書きしないうえ、拡張子が変わったファイル（`.locked` など）はフィルターで対象外になるため。

## 対策の一覧（優先度順）

| # | 優先度 | リスク | 対策 | 費用 | AWS の操作 |
|---|---|---|---|---|---|
| 1 | 高 | キーが漏れると、S3 の写真を**上書きで壊される** | S3 のバージョニングを有効にする（2026-11-02 に有効化済み） | 通常は 0 円 | 実施済み |
| 2 | 高 | ラズパイ・NAS・Immich がインターネットから見える | ポート開放・UPnP・WebAccess・Funnel を使わない | 0 円 | なし |
| 3 | 高 | ラズパイを乗っ取られると全部の鍵が取られる | SSH を鍵認証だけにし、OS を自動更新する | 0 円 | なし |
| 4 | 高 | 管理者や GitHub のアカウントを乗っ取られる | ルート・管理者・GitHub・Tailscale に MFA | 0 円 | なし（確認だけ） |
| 5 | 中 | Immich の弱いパスワードや古いバージョン | パスワードを変え、定期的に更新する | 0 円 | なし |
| 6 | 中 | NAS の SMB1・古いファームウェア | SMB2 以上を使い、ファームウェアを最新にする | 0 円 | なし |
| 7 | 中 | キーの漏えいやバックアップ停止に気づけない | キーを年1回入れ替え、失敗を通知する | 0 円 | あり（キー発行時に要確認） |
| 8 | 低 | ほかのバケットを誤って公開する | アカウント全体のパブリックアクセスブロック | 0 円 | あり（要確認） |

## 1. S3 のバージョニングを有効にする（高） {#versioning}

### なぜ必要か

`nas-backup` には削除権限がないが、`s3:PutObject` は**同じ名前で上書きする**こともできる。バージョニングが無効のままだと、アクセスキーが漏れた場合に、攻撃者が同じ名前のごみファイルで全写真を上書きでき、元の写真は戻らない（ランサムウェアがクラウドのバックアップを狙うときの典型的な手口）。

rclone の `--immutable` は「rclone 自身は上書きしない」という約束であって、キーを持った別の誰かは止められない。

### 対策

`infra/s3.tf` に `aws_s3_bucket_versioning`（`status = "Enabled"`）を追加する。上書きされても古い版が残り、`nas-backup` には古い版を消す権限（`s3:DeleteObjectVersion`）がないので、写真は守られる。

| 項目 | 内容 |
|---|---|
| 普段の費用 | 0 円。rclone は上書きしないので古い版ができない |
| 上書き攻撃を受けたとき | 上書き分の保管料がかかる。Budget Actions が予算超過で書き込みを止める |
| 仕様書との関係 | [仕様書の 5章](spec.md#s3)を「有効」に変更した（2026-11-02） |
| もっと強くするなら | Object Lock（管理者でも一定期間消せなくする）。ただし誤アップロードも消せなくなるので、今回は勧めない |

!!! warning "AWS の設定変更になる"
    `terraform apply` が必要。ユーザーの確認をとってから行う。一度有効にしたバージョニングは「停止」はできるが「無効」には戻せない。

## 2. 外から見えないようにする（高）

今の設計（ポート開放なし、外からは Tailscale）を崩さないことが一番大事。次の 5 つは**やらない・確認する**。

- **ルーターのポート開放をしない**: 2283（Immich）、22（SSH）、445（SMB）は特に開けない
- **ルーターの UPnP を切る**: アプリが勝手にポートを開けるのを防ぐ
- **NAS の WebAccess（BuffaloNAS.com）を切る**: NAS の写真フォルダに `.webaxs` ができているので、WebAccess が有効になっている可能性がある。有効だと NAS がインターネットに出る。LS220D は古い機種なので、外に出すのは特に避ける。外から写真を見るのは Immich＋Tailscale に任せる
- **`tailscale funnel` を使わない**: `tailscale serve` は自分の tailnet の中だけだが、`funnel` は**インターネットに公開**する。名前が似ているので注意
- **IPv6 で外から届かないか確認する**: IPv6（IPoE）回線では、ラズパイに外から届く IPv6 アドレスが付くことがある。ルーターの IPv6 ファイアウォール（「IPv6 通信を許可しない」などの設定）が有効か確認する

!!! note "ufw などのファイアウォールは Docker のポートを止めない"
    Docker は iptables を直接書き換えるため、ラズパイで `ufw` を設定しても、`ports: '2283:2283'` で公開したポートには効かない。Immich を守るのは「ルーターで開けない」こと。

## 3. ラズパイを守る（高）

ラズパイには NAS のパスワード（`/etc/nas-credentials`）、AWS のキー（`rclone.conf`）、GitHub のデプロイキー、Immich の DB が全部ある。さらに `pi` ユーザーは `docker` グループに入っているので、実質 root と同じ。ラズパイを乗っ取られると全部取られる前提で、入口を固める。

```
# 1) PC で SSH 鍵を作ってラズパイに登録（PC 側で実行）
ssh-keygen -t ed25519
ssh-copy-id pi@<ラズパイのIP>

# 2) ラズパイでパスワードログインと root ログインを止める
#    10-hardening.conf は新しく作るファイル。sshd_config.d/ は先に読んだ値が優先されるので 10- で始める
grep Include /etc/ssh/sshd_config   # Include /etc/ssh/sshd_config.d/*.conf があることを確認
sudo tee /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t                                                       # 書き間違いがないか確認
sudo sshd -T | grep -E 'passwordauthentication|permitrootlogin'    # どちらも no になっていること
sudo systemctl restart ssh     # 別のターミナルで鍵ログインできることを確かめてから閉じる

# 3) セキュリティ更新を自動で入れる
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

- `pi` ユーザーのパスワードは長いものにする（`sudo` で使う）
- 家の外から SSH したい場合も、ポート開放ではなく Tailscale 経由にする

## 4. アカウントに MFA を付ける（高）

S3 の写真を確実に消せるのは管理者だけ。管理者を乗っ取られると、どの対策も効かない。

| アカウント | 確認すること |
|---|---|
| AWS ルートユーザー | MFA が付いている。普段は使わない |
| AWS 管理者（`nas-admin`） | MFA（パスキーか FIDO2 キー）。**アクセスキーを作らない**（`aws login` を使う） |
| GitHub アカウント | 2 段階認証。ラズパイはこのリポジトリのコードをそのまま実行するため |
| Tailscale のログインアカウント（Google など） | 2 段階認証。乗っ取られると自分の tailnet に端末を足される |

Tailscale は管理画面の「Device approval」を有効にすると、新しい端末を足すときに承認が必要になる（任意）。

## 5. Immich（中）

- `.env` の `DB_PASSWORD` を `change-me` のままにしない（`openssl rand -hex 24`）
- Immich の管理者パスワードは長いものにする。ユーザーを増やすときは管理者が作る
- 共有リンクは Tailscale の中でしか開けない。家族に外から見せたいときも Funnel ではなく、家族の端末を Tailscale に入れる
- 更新を止めない。月に1回くらい [リリースノート](https://github.com/immich-app/immich/releases) を見て `docker compose pull && docker compose up -d`。`newVersionCheck` が有効なので、新しい版があると画面に出る
- 任意: 家でも Tailscale を使うなら、`ports` を `'127.0.0.1:2283:2283'` にして `tailscale serve` の HTTPS だけで開くようにできる。LAN 内の HTTP（パスワードが平文で流れる）をなくせるが、Tailscale を入れていない端末からは開けなくなる。家庭の LAN なら今のままでもよい

## 6. NAS（中）

- fstab の `vers=1.0` は**使わないで済むならそのまま `vers=2.0`（以上）** にする。SMB1 は WannaCry などで狙われた古い方式。どうしても 1.0 でしかつながらない場合は、LAN の中だけで使い、NAS を外に出さない（2）ことを徹底する
- NAS の管理画面でファームウェアを最新にする。管理者パスワードを初期値から変える
- PC からの保存に使う NAS ユーザーは、`nas-pi` と分けたまま使う

## 7. キーの入れ替えと通知（中）

- `nas-backup` のアクセスキーを**年に1回入れ替える**。新しいキーを発行 → `rclone.conf` を書き換え → 動作確認 → 古いキーを削除。キーの発行と削除は AWS の操作なので、実行前に確認をとる
- IAM のコンソールで、キーの「最終使用日時」がラズパイのバックアップ時刻（02:00 ごろ）以外になっていないかをたまに見る
- バックアップ失敗の通知（[仕様書の 11章 未決事項](spec.md#open-issues)）は、セキュリティの面でも役に立つ。書き込みが自動停止されたときや、写真が書き換えられて `--immutable` がエラーを出したときに気づけるため

## 8. アカウント全体のパブリックアクセスブロック（低）

バケット単位ではすでにブロックしている。アカウント全体でもオンにすると、これから作るバケットも含めて公開できなくなる（無料）。AWS の設定変更なので、行う場合は事前に確認をとる。

## 検討したが今は不要なもの

| 案 | 不要とした理由 |
|---|---|
| rclone の暗号化（crypt）で S3 に入れる前に暗号化する | パスワードをなくすと写真を戻せない。今から切り替えると全部をアップロードし直す費用と、180日以内の削除課金がかかる。SSE-S3 とアクセス制御で十分 |
| `rclone.conf` 自体を暗号化する | 毎晩の自動実行のためにパスワードをラズパイに置くことになり、効果が小さい |
| アクセス元 IP で `nas-backup` を制限する | 家の回線の IP が変わるとバックアップが止まる |
| バケットポリシーで上書きを禁止する（条件付き書き込み `If-None-Match: *` を必須にする） | IAM だけでは「新規は可、上書きは不可」を書けず、[条件付き書き込みの強制](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html)が必要。しかし rclone は S3 へのアップロードで `If-None-Match` を送れない（`--header-upload` でも無視される。[rclone フォーラム](https://forum.rclone.org/t/does-rclone-s3-support-if-none-match-and-if-match-upload-headers/52961)）ため、入れるとバックアップがすべて失敗する。代わりにバージョニング（1）で古い版を残す |
| GuardDuty などの有料の監視 | 費用に対して効果が小さい。異常検知（無料）で足りる |
| KMS（SSE-KMS）の暗号化 | 料金がかかり、この用途では SSE-S3 と差がない |
