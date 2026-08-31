# RoleCallAI documentation

| Document | Audience | Purpose |
| --- | --- | --- |
| [Reproducible testing](REPRODUCIBLE_TESTING.md) | Judges and reviewers | Test the hosted application or run the complete local suite. |
| [Self-hosting](SELF_HOSTING.md) | Cloud developers | Deploy safely into a separate Google Cloud project. |
| [Architecture](ARCHITECTURE.md) | Technical reviewers | Services, trust boundaries, nodes, pods, models, and cost-aware topology. |
| [Normal flow](FLOW.md) | Product and technical reviewers | Login-to-recap sequence plus meeting/runtime state machines. |
| [Hackathon guide](HACKATHON.md) | Judges and presenters | Four-minute story, eligibility evidence, and limitations. |
| [Lyria asset](LYRIA.md) | Maintainers | One-time music generation, provenance, data boundary, and cost guard. |
| [Deployment status](DEPLOYMENT.md) | Operators | Exact deployed revisions and acceptance evidence. |
| [Operations](OPERATIONS.md) | Operators | Sleep/wake, credentials, documents, and incident procedures. |
| [Full teardown](FULL_TEARDOWN.md) | Owners | Destructive deletion and recreation boundary. |
| [Specifications](specs/README.md) | Contributors | Spec-driven development and traceability. |

The source of truth for current cloud cost assumptions is
[infra/terraform/COST_ESTIMATE.md](../infra/terraform/COST_ESTIMATE.md).
