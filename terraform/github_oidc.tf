data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_role" "github_actions" {
  name = "ShipZenGitHubActionsRole"
}

