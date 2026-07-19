# ShipZen Agent Rules

## Git Workflow
- **Commit After Fixes**: After fixing a bug or completing a change, you must automatically use the `run_command` tool to stage (`git add`) and commit (`git commit -m "..."`) the changes on behalf of the user. Do not wait for the user to ask you to commit.

## Infrastructure & Kubernetes Lessons
- **Kyverno PolicyExceptions**: When writing a `PolicyException` for Kyverno to bypass rules on Pod-controllers (DaemonSets, Deployments), the webhook evaluates against the auto-generated rules (`autogen-`). To ensure it matches both the controller and the pods, you must specify BOTH the original rule name (e.g. `host-namespaces`) AND the auto-generated name (`autogen-host-namespaces`) in the `ruleNames` array. Also, ensure you target the exact APIGroup in `Kinds` (e.g. `apps/v1/DaemonSet`).
- **Terraform local-exec pipelines**: When using `local-exec` to pipe `cat <<EOF` into `kubectl apply -f -`, be careful not to chain commands (like `aws eks update-kubeconfig`) in the same pipe sequence if they do not consume `stdin`. Run configuration commands on a separate line before piping the YAML to `kubectl`.
