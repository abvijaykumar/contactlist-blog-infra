"""An AWS Python Pulumi program"""

import pulumi
import pulumi_aws as aws
import provisioners
import base64
import json

config = pulumi.Config()

# Get the key configurations 
keyName = config.get('keyName')
publicKey = config.get('publicKey')

def decode_key(key):

    try:
        key = base64.b64decode(key.encode('ascii')).decode('ascii')
    except:
        pass

    if key.startswith('-----BEGIN RSA PRIVATE KEY-----'):
        return key

    return key.encode('ascii')

privateKey = config.require_secret('privateKey').apply(decode_key)
privateKeyPassPhrase = config.get_secret('privateKeyPassphrase')

# if the keyname is empty, then create a new key
if keyName is None:
    key = aws.ec2.KeyPair('pulumi-blog-key', public_key=publicKey)
    keyName = key.key_name



# create a VPC
myvpc = aws.ec2.Vpc("pulumi-blog-vpc", cidr_block="10.0.0.0/16",
    tags={
        "Name": "pulumi-blog-vpc",
    })
myvpcid = myvpc.id
pulumi.export('vpc', myvpc.id)

# create internet gateway instance
igw = aws.ec2.InternetGateway("pulumi-blog-igw",
    vpc_id=myvpcid,
    tags={
        "Name": "pulumi-blog-igw",
    })
#create a public subnet
subnet = aws.ec2.Subnet("pulumi-blog-subnet",
    vpc_id=myvpcid,
    cidr_block="10.0.1.0/24",
    map_public_ip_on_launch=True,
    tags={
        "Name": "pulumi-blog-subnet",
    })


# add a route 
route = aws.ec2.Route("pulumi-blog-route",
    route_table_id=myvpc.default_route_table_id,
    destination_cidr_block="0.0.0.0/0",
    gateway_id=igw.id
    )


mysecgroup = aws.ec2.SecurityGroup('pulumi-blog-secgrp',
    description='Enable HTTP access',
    tags={
        "Name": "pulumi-blog-sg",
    },
    vpc_id=myvpcid,
    ingress=[aws.ec2.SecurityGroupIngressArgs(
        protocol='tcp',
        from_port=8082,
        to_port=8082,
        cidr_blocks=['0.0.0.0/0'],
    ),
    aws.ec2.SecurityGroupIngressArgs(
        protocol='tcp',
        from_port=22,
        to_port=22,
        cidr_blocks=['0.0.0.0/0'],
    ), 
    aws.ec2.SecurityGroupIngressArgs(
        protocol='tcp',
        from_port=8081,
        to_port=8081,
        cidr_blocks=['0.0.0.0/0'],
    )
    ],
    
    
    egress=[aws.ec2.SecurityGroupEgressArgs(
        from_port=0,
        to_port=0,
        protocol="-1",
        cidr_blocks=["0.0.0.0/0"],
        ipv6_cidr_blocks=["::/0"],
    )])
    
# create the dynamodb
contacts_dynamodb_table = aws.dynamodb.Table(resource_name="contacts-table",name="contacts-table",
    attributes=[
        aws.dynamodb.TableAttributeArgs(
            name="ContactName",
            type="S",
        ),
        aws.dynamodb.TableAttributeArgs(
            name="ContactNumber",
            type="S",
        ),
    ],
    hash_key="ContactNumber",
    billing_mode="PROVISIONED",
    read_capacity=20,
    global_secondary_indexes=[aws.dynamodb.TableGlobalSecondaryIndexArgs(
        hash_key="ContactName",
        name="NameIndex",
        non_key_attributes=["ContactNumber"],
        projection_type="INCLUDE",
        read_capacity=10,
        write_capacity=10,
    )],
    tags={
        "env": "dev",
        "Name": "contacts-table",
    },
    write_capacity=20)

dynamodb_arn = contacts_dynamodb_table.arn
pulumi.export('dynamodb arn', contacts_dynamodb_table.arn)
pulumi.export('dynamodb id', contacts_dynamodb_table.id)
pulumi.export('dynamodb stream arn', contacts_dynamodb_table.stream_arn)
pulumi.export('dynamodb label', contacts_dynamodb_table.stream_label)


#Setup VPC endpoint to the dynmodb
vpcep = aws.ec2.VpcEndpoint("dynamodb",
    vpc_id=myvpcid,
    service_name="com.amazonaws.us-east-1.dynamodb")
pulumi.export('VPC Endpoint arn', vpcep.arn)
pulumi.export('VPC Endpoint id', vpcep.id)


# Search for the right AMI and create a EC2 instance
#create IAM Role - We will need this when we go to the GitOps
ec2_role = aws.iam.Role("pulumi-blog-ec2-role", name="pulumi-blog-ec2-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                "Service": "ec2.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
            ]
    }),
    tags={
        "Name": "pulumi-blog-ec2-role",
    })


dynamodb_policy = aws.iam.Policy("dynamodb_access_policy_1",
    description="Access DynamoDB from EC2",
    policy={
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DescribeQueryScanBooksTable",
            "Effect": "Allow",
            "Action": [
                "dynamodb:BatchGet*",
                "dynamodb:DescribeStream",
                "dynamodb:DescribeTable",
                "dynamodb:Get*",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:BatchWrite*",
                "dynamodb:CreateTable",
                "dynamodb:Delete*",
                "dynamodb:Update*",
                "dynamodb:PutItem"            
            ],
            "Resource": contacts_dynamodb_table.arn
    }]})

dynamodb_policy_attach = aws.iam.RolePolicyAttachment("dynamodb_policy_attach ",
    role=ec2_role.id,
    policy_arn=dynamodb_policy.arn)

dynamodb_access_policy = aws.iam.RolePolicyAttachment("dynamodb_access_policy_2",
    role=ec2_role.id,
    policy_arn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
)



linuxami = aws.ec2.get_ami(most_recent=True,
   filters=[aws.ec2.GetAmiFilterArgs(
        name='name',
        values=['amzn2-ami-hvm-2.0.????????-x86_64-gp2'],
    )],
    owners=["amazon"])

user_data = """
#!/bin/bash
sudo yum update && sudo yum -y install curl
curl -sL https://rpm.nodesource.com/setup_16.x | sudo bash -
sudo yum install -y nodejs
sudo yum -y install gcc-c++ make
curl -sL https://dl.yarnpkg.com/rpm/yarn.repo | sudo tee /etc/yum.repos.d/yarn.repo
sudo yum -y install yarn
node --version
sudo yum install -y ruby
sudo yum install wget
wget https://aws-codedeploy-ap-south-1.s3.ap-south-1.amazonaws.com/latest/install
chmod +x ./install
sudo ./install auto
sudo service codedeploy-agent start 
"""
instance_profile = aws.iam.InstanceProfile("pulumi-blog-instance-profile", name="pulumi-blog-ec2-role", role=ec2_role.name)
myinstance = aws.ec2.Instance("pulumi-blog-instance",
    ami=linuxami.id,
    instance_type="t2.micro",
    user_data=user_data,
    iam_instance_profile=instance_profile,
    tags={
        "Name": "pulumi-blog-instance",
    },
    vpc_security_group_ids=[mysecgroup.id],
    subnet_id=subnet.id,
    key_name=keyName
    #metadata_options=instance_metadata_options
    )

pulumi.export('public_ip', myinstance.public_ip)
pulumi.export('public_dns', myinstance.public_dns)
    
conn = provisioners.ConnectionArgs(
    host=myinstance.public_ip,
    username='ec2-user',
    private_key=privateKey,
    private_key_passphrase=privateKeyPassPhrase,
)


"""
# Copy a config file to our server.
copy_cmd = provisioners.CopyFile('copy_cmd',
    conn=conn,
    src='node-install.sh',
    dest='node-install.sh',
    opts=pulumi.ResourceOptions(depends_on=[myinstance]),
)

run_shell_cmd = provisioners.RemoteExec('run_shell_cmd',
    conn=conn,
    commands=['sh node-install.sh >log.txt'],
    opts=pulumi.ResourceOptions(depends_on=[copy_cmd]),
)
"""


#Setup App GitOps
#Code eEploy Policy
codedeploy_role = aws.iam.Role("pulumi-blog-codedeploy-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
            "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "codedeploy.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
            ]
    }),
    tags={
        "Name": "pulumi-blog-codedeploy-role",
    })

ec2_role_policy_attachment = aws.iam.RolePolicyAttachment("pulumi-blog-ec2-role-policy-attach",
    role=ec2_role.id,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonEC2RoleforAWSCodeDeploy"
)

codedeploy_role_policy_attachment1 = aws.iam.RolePolicyAttachment("pulumi-blog-codedeploy-role-policy-attach1",
    role=codedeploy_role.id,
    policy_arn="arn:aws:iam::aws:policy/AmazonEC2FullAccess"
)
codedeploy_role_policy_attachment2 = aws.iam.RolePolicyAttachment("pulumi-blog-codedeploy-role-policy-attach2",
    role=codedeploy_role.id,
    policy_arn="arn:aws:iam::aws:policy/AWSCodeDeployFullAccess"
)
codedeploy_role_policy_attachment3 = aws.iam.RolePolicyAttachment("pulumi-blog-codedeploy-role-policy-attach3",
    role=codedeploy_role.id,
    policy_arn="arn:aws:iam::aws:policy/AdministratorAccess"
)
codedeploy_role_policy_attachment4 = aws.iam.RolePolicyAttachment("pulumi-blog-codedeploy-role-policy-attach4",
    role=codedeploy_role.id,
    policy_arn="arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
)
#Setup CodeDeploy Deploymnet group
code_deploy_app = aws.codedeploy.Application("pulumi-blog-codedeploy-app", 
        name="pulumi-blog-codedeploy-app",
        compute_platform="Server", 
        tags={
        "Name": "pulumi-blog-codedeploy-app",
        })
code_deploy_deploymnet_group = aws.codedeploy.DeploymentGroup("pulumi-blog-codedeploy-deploymentgroup",
    deployment_group_name="pulumi-blog-codedeploy-deploymentgroup",
    app_name=code_deploy_app.name, 
    service_role_arn=codedeploy_role.arn,
       ec2_tag_sets=[aws.codedeploy.DeploymentGroupEc2TagSetArgs(
        ec2_tag_filters=[
            aws.codedeploy.DeploymentGroupEc2TagSetEc2TagFilterArgs(
                key="Name",
                type="KEY_AND_VALUE",
                value="pulumi-blog-instance",
            ),
        ],
    )])


# storing the dynamodb table name on SSM
pulumi_blog_ssm = aws.ssm.get_parameter(name="pulumi-blog-ssm-dynamodb-name")
foo = aws.ssm.Parameter(resource_name=pulumi_blog_ssm.name, arn = pulumi_blog_ssm.arn,
    overwrite=True,
    type="String",
    value=contacts_dynamodb_table.id)


pulumi.export('SSM arn', pulumi_blog_ssm.arn)
pulumi.export('SSM name', pulumi_blog_ssm.name)
pulumi.export('SSM value', pulumi_blog_ssm.value)
