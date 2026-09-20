# Bootstrap: run ONCE, locally, with admin credentials (aws login).
#
# Creates the CI deploy role (GitHub OIDC, no stored keys), the events bucket
# the collectors push to and the demo build pulls from, and the EventBridge
# API destination that forwards App Runner / ECR events to /ingest/aws.
# Local state on purpose. The GitHub OIDC *provider* already exists in this
# account (created by data-qa-agent's bootstrap); this module only adds a role.
#
#   cd infra/terraform/bootstrap
#   terraform init && terraform apply -var ingest_url=https://<service>/ingest/aws -var ingest_secret=…

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "ap-southeast-2"
}

variable "project" {
  type    = string
  default = "pt"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role."
  type        = string
  default     = "nmp-dsci/productivity-tracker"
}

variable "tfstate_bucket" {
  type    = string
  default = "data-qa-tfstate-089783391188"
}

variable "ingest_url" {
  description = "Public /ingest/aws URL of the running service (set after the first deploy)."
  type        = string
  default     = ""
}

variable "ingest_secret" {
  description = "Bearer token the service expects on /ingest/aws (PT_INGEST_SECRET)."
  type        = string
  default     = ""
  sensitive   = true
}

data "aws_caller_identity" "current" {}

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# ── Events bucket ────────────────────────────────────────────────────────
# `pt sync push` mirrors data/events and data/rollups here; the deploy
# workflow pulls rollups/ into the image build context.

resource "aws_s3_bucket" "events" {
  bucket = "${var.project}-events-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "events" {
  bucket                  = aws_s3_bucket.events.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "events" {
  bucket = aws_s3_bucket.events.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "events" {
  bucket = aws_s3_bucket.events.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ── CI deploy role (GitHub OIDC) ─────────────────────────────────────────

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.project}-github-deploy"
  description        = "Assumed by GitHub Actions (OIDC) to deploy the ${var.project} demo and roll up events."
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "TerraformStateKey"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.tfstate_bucket}", "arn:aws:s3:::${var.tfstate_bucket}/${var.project}/*"]
  }
  statement {
    sid       = "EventsBucket"
    actions   = ["s3:GetObject", "s3:ListBucket", "s3:PutObject"]
    resources = [aws_s3_bucket.events.arn, "${aws_s3_bucket.events.arn}/*"]
  }
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "EcrRepo"
    actions   = ["ecr:*"]
    resources = ["arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/${var.project}-*"]
  }
  statement {
    sid       = "AppRunner"
    actions   = ["apprunner:*"]
    resources = ["*"]
  }
  statement {
    sid = "IamForServiceRoles"
    actions = [
      "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:TagRole", "iam:PassRole",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:GetRolePolicy", "iam:CreateServiceLinkedRole",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project}-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/*",
    ]
  }
  statement {
    sid = "Observability"
    actions = [
      "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource", "cloudwatch:TagResource",
      "logs:CreateLogGroup", "logs:DescribeLogGroups", "logs:PutRetentionPolicy", "logs:ListTagsForResource", "logs:TagResource",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${var.project}-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# ── Laptop collector identity ────────────────────────────────────────────
# `pt sync push` runs on the laptop under an SSO/`aws login` session; this
# policy is what that session needs, attachable to the permission set.

data "aws_iam_policy_document" "collector" {
  statement {
    actions   = ["s3:GetObject", "s3:ListBucket", "s3:PutObject"]
    resources = [aws_s3_bucket.events.arn, "${aws_s3_bucket.events.arn}/*"]
  }
  statement {
    actions   = ["ce:GetCostAndUsage", "apprunner:ListServices", "apprunner:ListOperations"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "collector" {
  name   = "${var.project}-collector"
  policy = data.aws_iam_policy_document.collector.json
}

# ── EventBridge → /ingest/aws (only once the service URL is known) ───────

resource "aws_cloudwatch_event_connection" "ingest" {
  count              = var.ingest_url == "" ? 0 : 1
  name               = "${var.project}-ingest"
  authorization_type = "API_KEY"
  auth_parameters {
    api_key {
      key   = "Authorization"
      value = "Bearer ${var.ingest_secret}"
    }
  }
}

resource "aws_cloudwatch_event_api_destination" "ingest" {
  count               = var.ingest_url == "" ? 0 : 1
  name                = "${var.project}-ingest"
  invocation_endpoint = var.ingest_url
  http_method         = "POST"
  connection_arn      = aws_cloudwatch_event_connection.ingest[0].arn
}

resource "aws_cloudwatch_event_rule" "deploys" {
  count = var.ingest_url == "" ? 0 : 1
  name  = "${var.project}-deploy-events"
  event_pattern = jsonencode({
    source = ["aws.apprunner", "aws.ecr"]
  })
}

data "aws_iam_policy_document" "events_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  count              = var.ingest_url == "" ? 0 : 1
  name               = "${var.project}-eventbridge-ingest"
  assume_role_policy = data.aws_iam_policy_document.events_trust.json
}

resource "aws_iam_role_policy" "events" {
  count = var.ingest_url == "" ? 0 : 1
  role  = aws_iam_role.events[0].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "events:InvokeApiDestination", Resource = aws_cloudwatch_event_api_destination.ingest[0].arn }]
  })
}

resource "aws_cloudwatch_event_target" "ingest" {
  count    = var.ingest_url == "" ? 0 : 1
  rule     = aws_cloudwatch_event_rule.deploys[0].name
  arn      = aws_cloudwatch_event_api_destination.ingest[0].arn
  role_arn = aws_iam_role.events[0].arn
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

output "events_bucket" {
  value = aws_s3_bucket.events.bucket
}

output "collector_policy_arn" {
  value = aws_iam_policy.collector.arn
}
