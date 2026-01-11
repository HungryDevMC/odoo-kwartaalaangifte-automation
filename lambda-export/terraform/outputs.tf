# ============================================================
# Odoo UBL Export Lambda - Outputs
# ============================================================

output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "export_endpoint" {
  description = "Export API endpoint"
  value       = "${aws_apigatewayv2_api.api.api_endpoint}/export"
}

output "download_endpoint" {
  description = "Download API endpoint"
  value       = "${aws_apigatewayv2_api.api.api_endpoint}/download/{filename}"
}

output "list_endpoint" {
  description = "List exports API endpoint"
  value       = "${aws_apigatewayv2_api.api.api_endpoint}/exports"
}

output "s3_bucket" {
  description = "S3 bucket for exports"
  value       = aws_s3_bucket.exports.bucket
}

output "lambda_function_name" {
  description = "Main Lambda function name"
  value       = aws_lambda_function.export.function_name
}

output "environment" {
  description = "Environment name"
  value       = var.environment
}

output "configured_filters" {
  description = "Configured export filters"
  value = {
    direction     = var.direction
    document_type = var.document_type
    state_filter  = var.state_filter
  }
}

