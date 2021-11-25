"""An AWS Python Pulumi program"""

import pulumi
import pulumi_aws as aws
import provisioners
import base64

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
        from_port=80,
        to_port=80,
        cidr_blocks=['0.0.0.0/0'],
    ),
    aws.ec2.SecurityGroupIngressArgs(
        protocol='tcp',
        from_port=22,
        to_port=22,
        cidr_blocks=['0.0.0.0/0'],
    )],
    
    
    egress=[aws.ec2.SecurityGroupEgressArgs(
        from_port=0,
        to_port=0,
        protocol="-1",
        cidr_blocks=["0.0.0.0/0"],
        ipv6_cidr_blocks=["::/0"],
    )]
    
    
    )
# create the dynamodb
contacts_dynamodb_table = aws.dynamodb.Table("contacts-table",
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
s3 = aws.ec2.VpcEndpoint("dynamodb",
    vpc_id=myvpcid,
    service_name="com.amazonaws.us-east-1.dynamodb")





# Search for the right AMI and create a EC2 instance
linuxami = aws.ec2.get_ami(most_recent=True,
   filters=[aws.ec2.GetAmiFilterArgs(
        name='name',
        values=['amzn2-ami-hvm-2.0.????????-x86_64-gp2'],
    )],
    owners=["amazon"])

user_data = """
#!/bin/bash

curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.32.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 7
"""

myinstance = aws.ec2.Instance("ipulumi-blog-instance",
    ami=linuxami.id,
    instance_type="t2.micro",
    user_data=user_data,
    tags={
        "Name": "pulumi-blog-instance",
    },
    vpc_security_group_ids=[mysecgroup.id],
    subnet_id=subnet.id,
    key_name=keyName,
    )

pulumi.export('public_ip', myinstance.public_ip)
pulumi.export('public_dns', myinstance.public_dns)
    
conn = provisioners.ConnectionArgs(
    host=myinstance.public_ip,
    username='ec2-user',
    private_key=privateKey,
    private_key_passphrase=privateKeyPassPhrase,
)


# Copy a config file to our server.
copy_cmd = provisioners.CopyFile('copy_cmd',
    conn=conn,
    src='node-install.sh',
    dest='node-install.sh',
    opts=pulumi.ResourceOptions(depends_on=[myinstance]),
)
"""
run_shell_cmd = provisioners.RemoteExec('run_shell_cmd',
    conn=conn,
    commands=['sh node-install.sh >log.txt'],
    opts=pulumi.ResourceOptions(depends_on=[copy_cmd]),
)

"""