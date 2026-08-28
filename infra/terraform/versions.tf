terraform {
  required_version = ">= 1.10.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.45"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 7.45"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_client_config" "current" {}

provider "kubernetes" {
  host                   = "https://${google_container_cluster.rolecall.endpoint}"
  cluster_ca_certificate = base64decode(google_container_cluster.rolecall.master_auth[0].cluster_ca_certificate)
  token                  = data.google_client_config.current.access_token
}

provider "helm" {
  kubernetes {
    host                   = "https://${google_container_cluster.rolecall.endpoint}"
    cluster_ca_certificate = base64decode(google_container_cluster.rolecall.master_auth[0].cluster_ca_certificate)
    token                  = data.google_client_config.current.access_token
  }
}
