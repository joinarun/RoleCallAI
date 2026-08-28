locals {
  notification_channels = var.notification_email == "" ? [] : [google_monitoring_notification_channel.email[0].name]
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.notification_email == "" ? 0 : 1
  display_name = "RoleCallAI development alerts"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
  force_delete = false
}

resource "google_logging_metric" "model_reconnects" {
  name        = "rolecall_model_reconnects"
  description = "Gemini Live session reconnect attempts without prompt or transcript content"
  filter      = "resource.type=\"k8s_container\" jsonPayload.message:\"event=model_reconnect\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "join_failures" {
  name        = "rolecall_join_failures"
  description = "Failed participant joins from Cloud Run request logs"
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${local.control_service_name}"
    httpRequest.requestMethod="POST"
    httpRequest.requestUrl:":join"
    httpRequest.status>=400
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "agent_audio_latency" {
  name            = "rolecall_agent_audio_latency_ms"
  description     = "Final participant caption to first agent audio frame"
  filter          = "resource.type=\"k8s_container\" jsonPayload.message:\"event=agent_audio_latency\""
  value_extractor = "REGEXP_EXTRACT(jsonPayload.message, \"latency_ms=([0-9.]+)\")"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
  }

  bucket_options {
    explicit_buckets {
      bounds = [100, 250, 500, 1000, 1500, 2500, 5000, 10000]
    }
  }
}

resource "google_logging_metric" "audio_gaps" {
  name        = "rolecall_audio_gaps"
  description = "Bounded audio input queue drops"
  filter      = "resource.type=\"k8s_container\" jsonPayload.message:\"event=audio_gap\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "pubsub_stuck" {
  display_name = "RoleCallAI stuck processing queue"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Oldest unacknowledged event exceeds five minutes"
    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\""
      comparison      = "COMPARISON_GT"
      threshold_value = 300
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.subscription_id"]
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "cloud_run_errors" {
  display_name = "RoleCallAI control plane 5xx responses"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Sustained control-plane server errors"
    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.label.service_name = \"${local.control_service_name}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.label.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05
      duration        = "120s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "model_reconnects" {
  display_name = "RoleCallAI repeated Gemini Live reconnects"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "More than three reconnects in five minutes"
    condition_threshold {
      filter          = "resource.type = \"k8s_container\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.model_reconnects.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 3
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "audio_gaps" {
  display_name = "RoleCallAI voice input audio gaps"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Any bounded audio queue overflow"
    condition_threshold {
      filter          = "resource.type = \"k8s_container\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.audio_gaps.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_dashboard" "rolecall" {
  dashboard_json = jsonencode({
    displayName = "RoleCallAI development"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          xPos = 0, yPos = 0, width = 6, height = 4
          widget = {
            title = "Cloud Run request latency"
            xyChart = {
              dataSets = [{
                plotType   = "LINE"
                targetAxis = "Y1"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_latencies\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_PERCENTILE_95"
                    }
                  }
                }
              }]
              yAxis = { label = "p95 latency (ms)", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 6, yPos = 0, width = 6, height = 4
          widget = {
            title = "Pub/Sub undelivered events"
            xyChart = {
              dataSets = [{
                plotType   = "STACKED_AREA"
                targetAxis = "Y1"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"pubsub_subscription\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MAX"
                    }
                  }
                }
              }]
              yAxis = { label = "messages", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 0, yPos = 4, width = 6, height = 4
          widget = {
            title = "GKE worker CPU"
            xyChart = {
              dataSets = [{
                plotType   = "LINE"
                targetAxis = "Y1"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"k8s_container\" AND metric.type=\"kubernetes.io/container/cpu/core_usage_time\" AND resource.label.namespace_name=\"rolecall\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
              }]
              yAxis = { label = "cores", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 6, yPos = 4, width = 6, height = 4
          widget = {
            title = "Model reconnects"
            xyChart = {
              dataSets = [{
                plotType = "LINE", targetAxis = "Y1", legendTemplate = "model reconnects"
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.model_reconnects.name}\""
                  aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_SUM" }
                } }
              }]
              yAxis = { label = "events", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 0, yPos = 8, width = 6, height = 4
          widget = {
            title = "Agent-audio p95 latency"
            xyChart = {
              dataSets = [{
                plotType = "LINE", targetAxis = "Y1", legendTemplate = "agent audio"
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.agent_audio_latency.name}\""
                  aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_PERCENTILE_95" }
                } }
              }]
              yAxis = { label = "milliseconds", scale = "LINEAR" }
            }
          }
        },
        {
          xPos = 6, yPos = 8, width = 6, height = 4
          widget = {
            title = "Active LiveKit rooms, join failures, and audio gaps"
            xyChart = {
              dataSets = [
                {
                  plotType = "LINE", targetAxis = "Y1", legendTemplate = "active rooms"
                  timeSeriesQuery = { timeSeriesFilter = {
                    filter      = "metric.type=\"prometheus.googleapis.com/livekit_room_total/gauge\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_MAX" }
                  } }
                },
                {
                  plotType = "LINE", targetAxis = "Y1", legendTemplate = "join failures"
                  timeSeriesQuery = { timeSeriesFilter = {
                    filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.join_failures.name}\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_SUM" }
                  } }
                },
                {
                  plotType = "LINE", targetAxis = "Y1", legendTemplate = "audio gaps"
                  timeSeriesQuery = { timeSeriesFilter = {
                    filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.audio_gaps.name}\""
                    aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_SUM" }
                  } }
                }
              ]
              yAxis = { label = "count", scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })

  # The Monitoring API injects server-owned name/etag fields into this JSON,
  # which otherwise creates a perpetual provider diff after every refresh.
  lifecycle {
    ignore_changes = [dashboard_json]
  }
}
