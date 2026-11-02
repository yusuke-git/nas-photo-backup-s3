# ラズパイ用のバックアップ専用ユーザー。削除と読み出しの権限は与えない。
# アクセスキーは Terraform の state に秘密情報を残さないよう、apply 後に AWS CLI で発行する（docs/setup-aws.md）。
resource "aws_iam_user" "backup" {
  name = var.backup_user_name
}

data "aws_iam_policy_document" "backup" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backup.arn]
  }

  statement {
    sid = "UploadOnly"
    actions = [
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.backup.arn}/*"]
  }
}

resource "aws_iam_user_policy" "backup" {
  name   = "nas-backup-upload-only"
  user   = aws_iam_user.backup.name
  policy = data.aws_iam_policy_document.backup.json
}
