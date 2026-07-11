# Minimal OpenTofu configuration used by CI and the demo workflow.
# No providers, no cloud: just hard-coded values shaped like real
# infrastructure outputs, so `tofu apply && tofu output -json` exercises
# the full pipeline end to end.

locals {
  subnets = [
    { az = "us-east-1a", cidr = "10.0.0.0/24", id = "subnet-053008016a2c1768c" },
    { az = "us-east-1b", cidr = "10.0.1.0/24", id = "subnet-07d4ce437c43eba2f" },
    { az = "us-east-1c", cidr = "10.0.2.0/24", id = "subnet-0a5f8c3a20023b8c0" },
  ]
}

output "cluster_endpoint" {
  description = "Kubernetes API endpoint"
  value       = "https://k8s.example.com:6443"
}

# Tofu drops `description` from `output -json`, so tofu-garnish also
# understands a sibling-output convention: `<name>_desc` is rendered as
# the description of `<name>` instead of its own card.
output "cluster_endpoint_desc" {
  value = "Kubernetes API endpoint for the primary cluster"
}

output "instance_count" {
  description = "Number of app instances"
  value       = 3
}

output "is_production" {
  description = "Whether this stack is production"
  value       = true
}

output "queue_arns" {
  description = "SQS queue ARNs"
  value = [
    "arn:aws:sqs:us-east-1:123456789012:orders",
    "arn:aws:sqs:us-east-1:123456789012:payments",
  ]
}

output "subnets" {
  description = "VPC subnets"
  value       = local.subnets
}

output "vpc" {
  description = "VPC attributes"
  value = {
    cidr_block = "10.0.0.0/16"
    id         = "vpc-01463b6b84e1454ce"
    tags = {
      Environment = "prod"
      Team        = "platform"
    }
  }
}

output "database_password" {
  description = "A sensitive value that must be masked on the page"
  value       = "s3cr3t-hunter2"
  sensitive   = true
}
