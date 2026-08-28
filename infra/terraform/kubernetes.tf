locals {
  nginx_common = {
    controller = {
      replicaCount = 1
      nodeSelector = {
        "rolecall-pool" = "workers"
      }
      service = {
        externalTrafficPolicy = "Local"
        annotations = {
          "cloud.google.com/l4-rbs" = "enabled"
        }
      }
      config = {
        "enable-access-log"         = "false"
        "server-tokens"             = "false"
        "strict-validate-path-type" = "false"
      }
      metrics = {
        enabled = true
      }
    }
  }
}

resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = var.cert_manager_chart_version
  namespace        = "cert-manager"
  create_namespace = true
  atomic           = true
  wait             = true
  timeout          = 900

  values = [yamlencode({
    crds       = { enabled = true }
    prometheus = { enabled = true }
  })]

  depends_on = [
    google_container_node_pool.workers,
    google_container_node_pool.media,
  ]
}

resource "helm_release" "ingress_signal" {
  name             = "ingress-signal"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = var.ingress_nginx_chart_version
  namespace        = "ingress-signal"
  create_namespace = true
  atomic           = true
  wait             = true
  timeout          = 900

  values = [yamlencode(merge(local.nginx_common, {
    controller = merge(local.nginx_common.controller, {
      electionID   = "rolecall-signal-leader"
      ingressClass = "rolecall-signal"
      ingressClassResource = {
        name            = "rolecall-signal"
        enabled         = true
        default         = false
        controllerValue = "rolecall.ai/ingress-signal"
      }
      service = merge(local.nginx_common.controller.service, {
        loadBalancerIP = google_compute_address.livekit_signaling.address
      })
    })
  }))]

  depends_on = [google_container_node_pool.workers]
}

resource "helm_release" "ingress_turn" {
  name             = "ingress-turn"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = var.ingress_nginx_chart_version
  namespace        = "ingress-turn"
  create_namespace = true
  atomic           = true
  wait             = true
  timeout          = 900

  values = [yamlencode(merge(local.nginx_common, {
    controller = merge(local.nginx_common.controller, {
      electionID   = "rolecall-turn-leader"
      ingressClass = "rolecall-turn"
      ingressClassResource = {
        name            = "rolecall-turn"
        enabled         = true
        default         = false
        controllerValue = "rolecall.ai/ingress-turn"
      }
      service = merge(local.nginx_common.controller.service, {
        loadBalancerIP = google_compute_address.livekit_turn.address
        enableHttps    = false
      })
    })
    tcp = {
      "5349" = "rolecall/livekit-turn:5349"
    }
    udp = {
      "3478" = "rolecall/livekit-turn:3478"
    }
  }))]

  depends_on = [google_container_node_pool.workers]
}

resource "helm_release" "platform" {
  name             = "rolecall-platform"
  chart            = "${path.module}/../kubernetes/platform"
  namespace        = "rolecall"
  create_namespace = true
  atomic           = true
  wait             = true
  timeout          = 900

  values = [yamlencode({
    acmeEmail      = var.acme_email
    signalHostname = local.livekit_hostname
    turnHostname   = local.turn_hostname
    signalClass    = "rolecall-signal"
    turnClass      = "rolecall-turn"
    livekitService = "livekit-server"
  })]

  set_sensitive {
    name  = "secrets.livekitApiKey"
    value = random_id.livekit_api_key.hex
  }
  set_sensitive {
    name  = "secrets.livekitApiSecret"
    value = random_password.livekit_api_secret.result
  }

  depends_on = [
    helm_release.cert_manager,
    helm_release.ingress_signal,
    helm_release.ingress_turn,
  ]
}

resource "helm_release" "livekit" {
  name       = "livekit"
  repository = "https://helm.livekit.io"
  chart      = "livekit-server"
  version    = var.livekit_chart_version
  namespace  = "rolecall"
  atomic     = true
  wait       = true
  timeout    = 1200

  values = [yamlencode({
    fullnameOverride              = "livekit-server"
    replicaCount                  = var.media_min_nodes
    podHostNetwork                = true
    terminationGracePeriodSeconds = 18000
    image = {
      repository = "livekit/livekit-server"
      tag        = "v${var.livekit_server_version}"
      pullPolicy = "IfNotPresent"
    }
    livekit = {
      port            = 7880
      prometheus_port = 6789
      # INFO includes ephemeral TURN credentials and WARN can include failed data
      # payloads. Application-level alerts retain the actionable voice signals.
      log_level = "error"
      key_file  = "keys.yaml"
      rtc = {
        tcp_port         = 7881
        port_range_start = 50000
        port_range_end   = 60000
        use_external_ip  = true
      }
      redis = {
        address = "${google_redis_instance.rolecall.host}:${google_redis_instance.rolecall.port}"
      }
      turn = {
        enabled     = true
        domain      = local.turn_hostname
        tls_port    = 5349
        udp_port    = 3478
        secretName  = "livekit-turn-tls"
        serviceType = "ClusterIP"
      }
      webhook = {
        urls = ["${local.control_url}/v1/internal/livekit/webhook"]
      }
      room = {
        auto_create = false
      }
    }
    storeKeysInSecret = {
      enabled        = true
      existingSecret = "livekit-credentials"
    }
    loadBalancer = {
      type        = "disable"
      servicePort = 7880
    }
    turnLoadbalancer = {
      enable = false
    }
    autoscaling = {
      enabled                           = true
      minReplicas                       = var.media_min_nodes
      maxReplicas                       = var.media_max_nodes
      targetCPUUtilizationPercentage    = 65
      targetMemoryUtilizationPercentage = 75
    }
    nodeSelector = {
      "rolecall-pool" = "media"
    }
    tolerations = [{
      key      = "rolecall.ai/media"
      operator = "Equal"
      value    = "true"
      effect   = "NoSchedule"
    }]
    affinity = {
      podAntiAffinity = {
        requiredDuringSchedulingIgnoredDuringExecution = [{
          topologyKey = "kubernetes.io/hostname"
          labelSelector = {
            matchLabels = {
              "app.kubernetes.io/name"     = "livekit-server"
              "app.kubernetes.io/instance" = "livekit"
            }
          }
        }]
      }
    }
    deploymentStrategy = {
      type = "RollingUpdate"
      rollingUpdate = {
        maxSurge       = 1
        maxUnavailable = 0
      }
    }
    resources = {
      requests = { cpu = "1000m", memory = "2Gi" }
      limits   = { cpu = "4", memory = "4Gi" }
    }
    serviceMonitor = {
      create = false
    }
  })]

  set_sensitive {
    name  = "livekit.webhook.api_key"
    value = random_id.livekit_api_key.hex
  }

  depends_on = [
    helm_release.platform,
    google_cloud_run_v2_service.control,
    google_redis_instance.rolecall,
    google_container_node_pool.media,
  ]
}

resource "helm_release" "worker" {
  name      = "rolecall-worker"
  chart     = "${path.module}/../kubernetes/worker"
  namespace = "rolecall"
  atomic    = true
  wait      = true
  timeout   = 1200

  values = [yamlencode({
    image = {
      repository = split(":", local.images.worker)[0]
      tag        = var.image_tag
    }
    replicas    = var.worker_min_replicas
    maxReplicas = var.worker_max_replicas
    serviceAccount = {
      googleServiceAccount = google_service_account.rolecall["worker"].email
    }
    config = merge(local.common_env, {
      ROLECALL_LIVEKIT_URL  = "ws://livekit-server.rolecall.svc.cluster.local:7880"
      ROLECALL_SERVICE_NAME = "rolecall-worker"
      LIVEKIT_URL           = "ws://livekit-server.rolecall.svc.cluster.local:7880"
    })
    resources = {
      requests = { cpu = "500m", memory = "2Gi" }
      limits   = { cpu = "2", memory = "4Gi" }
    }
  })]

  set_sensitive {
    name  = "secrets.livekitApiKey"
    value = random_id.livekit_api_key.hex
  }
  set_sensitive {
    name  = "secrets.livekitApiSecret"
    value = random_password.livekit_api_secret.result
  }

  depends_on = [
    helm_release.livekit,
    google_service_account_iam_member.worker_identity,
  ]
}
