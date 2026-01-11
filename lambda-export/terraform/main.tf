# ============================================================
# Odoo UBL Export Lambda - Terraform Configuration
# ============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Backend configuration - use different keys per environment
  backend "s3" {
    # These values are set via -backend-config in the pipeline
    # bucket = "your-terraform-state-bucket"
    # key    = "odoo-ubl-export/${environment}/terraform.tfstate"
    # region = "eu-west-1"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "odoo-ubl-export"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ============================================================
# Local values
# ============================================================

locals {
  function_name     = "odoo-ubl-export-${var.environment}"
  lambda_source_dir = "${path.module}/.."
}

# ============================================================
# S3 Bucket for exports
# ============================================================

resource "aws_s3_bucket" "exports" {
  bucket = "${local.function_name}-exports"

  force_destroy = true # Allow deletion even if not empty

  tags = {
    Name = "${local.function_name}-exports"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    id     = "delete-old-exports"
    status = "Enabled"

    expiration {
      days = 30
    }

    filter {
      prefix = "exports/"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket = aws_s3_bucket.exports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ============================================================
# IAM Role for Lambda
# ============================================================

resource "aws_iam_role" "lambda" {
  name = "${local.function_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.function_name}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.exports.arn,
          "${aws_s3_bucket.exports.arn}/*"
        ]
      }
      # Note: No SES permissions needed - emails are sent via Odoo's mail system
    ]
  })
}

# ============================================================
# Lambda Layer (if needed for dependencies)
# ============================================================

# No external dependencies needed - using only stdlib + boto3

# ============================================================
# Package Lambda code
# ============================================================

# Lambda package - uses build directory created by CI pipeline (includes dependencies)
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${local.lambda_source_dir}/build"
  output_path = "${path.module}/lambda_function.zip"
}

# ============================================================
# Main Export Lambda Function
# ============================================================

resource "aws_lambda_function" "export" {
  function_name = "${local.function_name}-export"
  description   = "Export invoices from Odoo Online to UBL XML (${var.environment})"

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 256

  role = aws_iam_role.lambda.arn

  environment {
    variables = {
      # Odoo connection
      ODOO_URL      = var.odoo_url
      ODOO_DATABASE = var.odoo_database
      ODOO_USERNAME = var.odoo_username
      ODOO_API_KEY  = var.odoo_api_key
      # Filters
      DIRECTION     = var.direction
      DOCUMENT_TYPE = var.document_type
      STATE_FILTER  = var.state_filter
      CUSTOM_DOMAIN = var.custom_domain
      # Email (sent via Odoo's mail system)
      UBL_EMAIL = var.ubl_email
      PDF_EMAIL = var.pdf_email
      # Quarterly
      SEND_DAY                = tostring(var.send_day)
      BANK_JOURNAL_IDS        = var.bank_journal_ids
      INCLUDE_BANK_STATEMENTS = tostring(var.include_bank_statements)
      # S3
      S3_BUCKET = aws_s3_bucket.exports.bucket
    }
  }

  tags = {
    Name = "${local.function_name}-export"
  }
}

resource "aws_cloudwatch_log_group" "export" {
  name              = "/aws/lambda/${aws_lambda_function.export.function_name}"
  retention_in_days = 14
}

# ============================================================
# Download Lambda Function
# ============================================================

resource "aws_lambda_function" "download" {
  function_name = "${local.function_name}-download"
  description   = "Download exports from S3 (${var.environment})"

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "download_handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128

  role = aws_iam_role.lambda.arn

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.exports.bucket
    }
  }

  tags = {
    Name = "${local.function_name}-download"
  }
}

resource "aws_cloudwatch_log_group" "download" {
  name              = "/aws/lambda/${aws_lambda_function.download.function_name}"
  retention_in_days = 14
}

# ============================================================
# List Lambda Function
# ============================================================

resource "aws_lambda_function" "list" {
  function_name = "${local.function_name}-list"
  description   = "List available exports (${var.environment})"

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "list_handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128

  role = aws_iam_role.lambda.arn

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.exports.bucket
    }
  }

  tags = {
    Name = "${local.function_name}-list"
  }
}

resource "aws_cloudwatch_log_group" "list" {
  name              = "/aws/lambda/${aws_lambda_function.list.function_name}"
  retention_in_days = 14
}

# ============================================================
# API Gateway (HTTP API)
# ============================================================

resource "aws_apigatewayv2_api" "api" {
  name          = "${local.function_name}-api"
  protocol_type = "HTTP"
  description   = "Odoo UBL Export API (${var.environment})"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 300
  }

  tags = {
    Name = "${local.function_name}-api"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.function_name}"
  retention_in_days = 14
}

# Export endpoint
resource "aws_apigatewayv2_integration" "export" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.export.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "export" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "POST /export"
  target    = "integrations/${aws_apigatewayv2_integration.export.id}"
}

resource "aws_lambda_permission" "export" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.export.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# Download endpoint
resource "aws_apigatewayv2_integration" "download" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.download.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "download" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /download/{filename}"
  target    = "integrations/${aws_apigatewayv2_integration.download.id}"
}

resource "aws_lambda_permission" "download" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.download.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# List endpoint
resource "aws_apigatewayv2_integration" "list" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.list.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "list" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /exports"
  target    = "integrations/${aws_apigatewayv2_integration.list.id}"
}

resource "aws_lambda_permission" "list" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# ============================================================
# CloudWatch Event for Quarterly Auto-Send
# ============================================================

resource "aws_cloudwatch_event_rule" "quarterly" {
  name                = "${local.function_name}-quarterly"
  description         = "Trigger quarterly UBL export"
  schedule_expression = "cron(0 6 1-28 1,4,7,10 ? *)"
  state               = var.enable_quarterly_schedule ? "ENABLED" : "DISABLED"

  tags = {
    Name = "${local.function_name}-quarterly"
  }
}

resource "aws_cloudwatch_event_target" "quarterly" {
  rule      = aws_cloudwatch_event_rule.quarterly.name
  target_id = "quarterly-export"
  arn       = aws_lambda_function.export.arn
  input     = jsonencode({ auto_quarter = true })
}

resource "aws_lambda_permission" "quarterly" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.export.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.quarterly.arn
}

