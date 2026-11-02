output "bucket_name" {
  description = "backup.env の DEST に使うバケット名"
  value       = aws_s3_bucket.backup.bucket
}

output "backup_user_name" {
  description = "アクセスキーを発行する IAM ユーザー名"
  value       = aws_iam_user.backup.name
}

output "rclone_dest" {
  description = "backup.env の DEST にそのまま書ける値"
  value       = "s3backup:${aws_s3_bucket.backup.bucket}/photos"
}
