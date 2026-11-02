variable "region" {
  description = "バケットを作るリージョン。新しい AWS エクスペリエンスではプロジェクトのリージョン以外にリソースを作れない"
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  description = "terraform apply に使う AWS CLI のプロファイル名（管理者権限）"
  type        = string
  default     = "nas-admin"
}

variable "bucket_name" {
  description = "S3 バケット名（世界で一意にする必要がある）"
  type        = string
}

variable "budget_email" {
  description = "予算アラートの通知先メールアドレス"
  type        = string
}

variable "monthly_budget_usd" {
  description = "月額予算（USD）。実績が80%、予測が100%を超えるとメールで通知する"
  type        = number
  default     = 5
}

variable "backup_user_name" {
  description = "ラズパイの rclone が使う IAM ユーザー名"
  type        = string
  default     = "nas-backup"
}

variable "anomaly_threshold_usd" {
  description = "異常検知でメールを送る、想定外の課金額の下限（USD）"
  type        = number
  default     = 1
}
