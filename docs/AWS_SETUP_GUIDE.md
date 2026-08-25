# ShipZen AWS Setup Guide

This guide outlines the exact steps required to migrate the ShipZen infrastructure to a brand new AWS account.

## 1. AWS Account Creation & Security
1. Create a new AWS account at [aws.amazon.com](https://aws.amazon.com/).
2. Log in as the **Root User**.
3. Navigate to the **IAM Dashboard** and enable **MFA (Multi-Factor Authentication)** for the root user.
4. Navigate to the **Billing Console** -> **Credits** and apply your $200 promotional credit code.

## 2. Configure GitHub Actions Access (OIDC)
To allow GitHub Actions to safely deploy your infrastructure without using static access keys, you need to set up an OIDC identity provider.

1. In the AWS Console, go to **IAM** -> **Identity providers** -> **Add provider**.
2. Select **OpenID Connect**.
3. **Provider URL:** `https://token.actions.githubusercontent.com`
4. Click **Get thumbprint**.
5. **Audience:** `sts.amazonaws.com`
6. Click **Add provider**.

## 3. Create the Deployment IAM Role
1. Go to **IAM** -> **Roles** -> **Create role**.
2. Select **Web identity**.
3. **Identity provider:** Choose the GitHub provider you just created.
4. **Audience:** `sts.amazonaws.com`
5. **GitHub organization:** `jeneeldumasia`
6. **GitHub repository:** `ShipZen`
7. Click **Next**.
8. **Permissions:** Search for and attach **AdministratorAccess** (Terraform requires full permissions to create VPCs, EKS, IAM roles, etc.).
9. **Role name:** `shipzen-github-actions-role`
10. Click **Create role**.
11. Click into the new role and **copy the Role ARN** (e.g., `arn:aws:iam::123456789012:role/shipzen-github-actions-role`).

## 4. Update GitHub Secrets
1. Go to your ShipZen repository on GitHub -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Update the `AWS_ROLE_ARN` secret with the Role ARN you just copied.
3. Verify `AWS_REGION` is set to `ap-south-1`.

## 5. Clean up Terraform Cloud (HCP)
Since your Terraform state from the old account still exists, you must reset it so Terraform can build everything fresh.
1. Log into [Terraform Cloud (HCP)](https://app.terraform.io/).
2. Go to your `shipzen-prod` workspace.
3. Go to **Settings** -> **Destruction and Deletion**.
4. **Delete the workspace** (this deletes the old state file).
5. Recreate a new workspace named `shipzen-prod` in the `jeneel-shipzen` organization.
6. Ensure its Execution Mode is set to **Local** or **CLI-driven** (depending on your setup).
7. *(If you generated a new Terraform API token, update the `TF_API_TOKEN` secret in GitHub).* 

## 6. Deployment Sequence
1. Go to the GitHub Actions tab.
2. Run the **Deploy Platform Infra** workflow. This takes ~15-20 minutes to provision the VPC, EKS Cluster, databases, and ECR repositories.
3. Once successful, run the **Build and Push Docker Images** workflow to build your Python apps and push them to the newly created ECR repositories.
4. ArgoCD will automatically install onto the new cluster and pull in your Kubernetes manifests (`infra/` directory).

## 7. Post-Deployment Checks
- Run `aws eks update-kubeconfig --region ap-south-1 --name shipzen-cluster` to connect to your new cluster locally.
- Verify DNS routing in Cloudflare points to the new AWS Load Balancer.
