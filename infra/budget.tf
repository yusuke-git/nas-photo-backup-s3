# AWS Budgets は 2 個まで無料
resource "aws_budgets_budget" "monthly" {
  name         = "nas-photo-backup-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

# ---- 自動ストップ（Budget Actions） ----
# 実績が予算の100%に達したら、nas-backup ユーザーに書き込み拒否ポリシーを自動で付ける。
# キーが漏れて大量にアップロードされた場合に被害を止めるため。
# 解除は原因を確認してから、コンソールの Budgets でアクションを「元に戻す」か、ポリシーを手動で外す。

resource "aws_iam_policy" "backup_deny_write" {
  name        = "nas-backup-deny-write"
  description = "予算超過時に Budget Actions が nas-backup に付ける書き込み拒否ポリシー"
  policy      = data.aws_iam_policy_document.backup_deny_write.json
}

data "aws_iam_policy_document" "backup_deny_write" {
  statement {
    sid       = "DenyAllS3Writes"
    effect    = "Deny"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:ListBucket"]
    resources = [aws_s3_bucket.backup.arn, "${aws_s3_bucket.backup.arn}/*"]
  }
}

# Budgets がポリシーを付け外しするためのロール。対象は nas-backup と上の拒否ポリシーだけに絞る。
resource "aws_iam_role" "budget_action" {
  name               = "nas-backup-budget-action"
  assume_role_policy = data.aws_iam_policy_document.budget_action_assume.json
}

data "aws_iam_policy_document" "budget_action_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "budget_action" {
  name   = "attach-deny-to-nas-backup"
  role   = aws_iam_role.budget_action.id
  policy = data.aws_iam_policy_document.budget_action.json
}

data "aws_iam_policy_document" "budget_action" {
  statement {
    actions   = ["iam:AttachUserPolicy", "iam:DetachUserPolicy"]
    resources = [aws_iam_user.backup.arn]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [aws_iam_policy.backup_deny_write.arn]
    }
  }
}

resource "aws_budgets_budget_action" "stop_backup_writes" {
  budget_name        = aws_budgets_budget.monthly.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.backup_deny_write.arn
      users      = [aws_iam_user.backup.name]
    }
  }

  subscriber {
    address           = var.budget_email
    subscription_type = "EMAIL"
  }
}

# ---- 異常検知（Cost Anomaly Detection） ----
# サービスごとの普段の課金パターンを学習し、急増したらメールで知らせる（無料）。
# EC2 など使っていないサービスに課金が出た場合にも気づける。

resource "aws_ce_anomaly_monitor" "services" {
  name              = "nas-photo-backup-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "email" {
  name             = "nas-photo-backup-anomaly"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "EMAIL"
    address = var.budget_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_threshold_usd)]
    }
  }
}
