terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {source = "hashicorp/aws", version = "~> 5.0"}
  }
}
provider "aws" { region = var.aws_region }
variable "aws_region" { type = string; default = "ap-south-1" }
variable "project" { type = string; default = "rollit-demo" }
# Low-cost cloud component: S3 bucket for versioned deployment evidence.
# Application deployment remains local until a production runtime is configured.
resource "aws_s3_bucket" "release_audit" {
  bucket_prefix = "${var.project}-audit-"
  tags = { Project = var.project, ManagedBy = "Terraform" }
}
resource "aws_s3_bucket_versioning" "release_audit" {
  bucket = aws_s3_bucket.release_audit.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_public_access_block" "release_audit" {
  bucket = aws_s3_bucket.release_audit.id
  block_public_acls = true
  block_public_policy = true
  ignore_public_acls = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "release_audit" {
  bucket = aws_s3_bucket.release_audit.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}
output "audit_bucket" { value = aws_s3_bucket.release_audit.bucket }
