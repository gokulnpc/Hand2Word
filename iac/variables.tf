variable "region" {
  description = "The AWS region to deploy resources in"
  default     = "us-east-1"
}

variable "kubernetes_version" {
  description = "Kubernetes version for the EKS cluster"
  default     = "1.28"
}

variable "instance_type" {
  description = "EC2 instance type for the EKS worker nodes"
  default     = "t3.small"
}

variable "disk_size" {
  description = "Disk size in GB for the EKS worker nodes"
  default     = 20
}

variable "desired_capacity" {
  description = "Desired number of worker nodes"
  default     = 1
}

variable "max_capacity" {
  description = "Maximum number of worker nodes"
  default     = 2
}

variable "min_capacity" {
  description = "Minimum number of worker nodes"
  default     = 1
}

variable "api_gateway_stage" {
  description = "API Gateway stage name"
  default     = "dev"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  default     = "dev"
}

variable "mongodb_url" {
  description = "MongoDB Atlas connection string"
  type        = string
  sensitive   = true
  default     = ""
}