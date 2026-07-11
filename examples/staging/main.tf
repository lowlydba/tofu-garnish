# A second tiny config so CI and the demo can exercise discrete
# multi-workspace publishing (e.g. a staging tenant applied separately).

output "service_hostname" {
  description = "Public hostname"
  value       = "staging.example.com"
}

output "instance_count" {
  description = "Number of app instances"
  value       = 1
}

output "vpc" {
  description = "VPC attributes"
  value = {
    cidr_block = "10.1.0.0/16"
    id         = "vpc-0staging1234567890"
    tags = {
      Environment = "staging"
      Team        = "platform"
    }
  }
}
