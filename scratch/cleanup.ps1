$ErrorActionPreference = "SilentlyContinue"

Write-Host "Deleting ECR Repository..."
aws ecr delete-repository --repository-name "deployhub-builds" --force

Write-Host "Deleting IAM Policies..."
$policies = @("DeployHubGitHubActionsPolicy", "DeployHubALBControllerPolicy")
foreach ($p in $policies) {
    $arn = "arn:aws:iam::952994886652:policy/$p"
    aws iam delete-policy --policy-arn $arn
}

Write-Host "Deleting CloudWatch Log Group..."
aws logs delete-log-group --log-group-name "/aws/eks/deployhub-cluster/cluster"

Write-Host "Deleting KMS Alias..."
aws kms delete-alias --alias-name "alias/eks/deployhub-cluster"

Write-Host "Finding and Deleting VPCs..."
$vpcs = aws ec2 describe-vpcs --filters "Name=tag:Name,Values=deployhub-vpc" --query "Vpcs[*].VpcId" --output text
if ($vpcs) {
    $vpcList = $vpcs -split '\s+'
    foreach ($vpc in $vpcList) {
        if (-not [string]::IsNullOrWhiteSpace($vpc)) {
            Write-Host "Cleaning up VPC $vpc"
            
            # Delete NAT Gateways
            $nats = aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$vpc" "Name=state,Values=available,pending" --query "NatGateways[*].NatGatewayId" --output text
            if ($nats) {
                foreach ($nat in ($nats -split '\s+')) {
                    if ($nat) {
                        Write-Host "  Deleting NAT $nat"
                        aws ec2 delete-nat-gateway --nat-gateway-id $nat
                    }
                }
                Write-Host "  Waiting for NATs to delete (30s)..."
                Start-Sleep -Seconds 30
            }

            # Delete Internet Gateways
            $igws = aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$vpc" --query "InternetGateways[*].InternetGatewayId" --output text
            if ($igws) {
                foreach ($igw in ($igws -split '\s+')) {
                    if ($igw) {
                        Write-Host "  Detaching and Deleting IGW $igw"
                        aws ec2 detach-internet-gateway --internet-gateway-id $igw --vpc-id $vpc
                        aws ec2 delete-internet-gateway --internet-gateway-id $igw
                    }
                }
            }

            # Delete Subnets
            $subnets = aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" --query "Subnets[*].SubnetId" --output text
            if ($subnets) {
                foreach ($sub in ($subnets -split '\s+')) {
                    if ($sub) {
                        Write-Host "  Deleting Subnet $sub"
                        aws ec2 delete-subnet --subnet-id $sub
                    }
                }
            }

            # Delete Route Tables
            $rtbs = aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$vpc" --query "RouteTables[?Associations[0].Main!=\`true\`].RouteTableId" --output text
            if ($rtbs) {
                foreach ($rtb in ($rtbs -split '\s+')) {
                    if ($rtb) {
                        Write-Host "  Deleting Route Table $rtb"
                        aws ec2 delete-route-table --route-table-id $rtb
                    }
                }
            }

            # Delete Security Groups
            $sgs = aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" --query "SecurityGroups[?GroupName!='default'].GroupId" --output text
            if ($sgs) {
                foreach ($sg in ($sgs -split '\s+')) {
                    if ($sg) {
                        Write-Host "  Deleting Security Group $sg"
                        aws ec2 delete-security-group --group-id $sg
                    }
                }
            }

            # Delete VPC
            Write-Host "  Deleting VPC $vpc"
            aws ec2 delete-vpc --vpc-id $vpc
        }
    }
}

Write-Host "Cleanup script complete."
