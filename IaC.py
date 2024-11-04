provider "aws" {
  region = "us-east-2"
}

terraform {
  required_version = ">= 0.14"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.0"
    }
  }
}

# 가용 영역 데이터 소스 선언
data "aws_availability_zones" "available" {}

# VPC 및 서브넷 생성
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  
  tags = {
    name = "terraform-test" 
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  map_public_ip_on_launch = true
  availability_zone       = element(data.aws_availability_zones.available.names, count.index)
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 2)
  availability_zone = element(data.aws_availability_zones.available.names, count.index)
}

# 인터넷 게이트웨이 생성
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "terraform-igw"
  }
}

# 퍼블릭 서브넷용 라우팅 테이블 생성
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "terraform-public-rt"
  }
}

# 퍼블릭 서브넷과 라우팅 테이블 연결
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Bastion 호스트 생성
resource "aws_instance" "bastion" {
  ami           = "ami-09da212cf18033880" # us-east-2 리전의 실제 AMI ID
  instance_type = "t2.micro"
  subnet_id     = aws_subnet.public[0].id
  key_name      = "nm-pr-key" # 실제 키 쌍 이름

  tags = {
    Name = "Bastion Host"
  }
}

# 애플리케이션 서버를 위한 Launch Template 생성
resource "aws_launch_template" "app" {
  name_prefix   = "app-launch-template"
  image_id      = "ami-09da212cf18033880" # us-east-2 리전의 실제 AMI ID
  instance_type = "t2.micro"
  key_name      = "nm-pr-key" # 실제 키 쌍 이름

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "app" {
  vpc_zone_identifier = aws_subnet.private[*].id
  launch_template {
    id      = aws_launch_template.app.id
    version = "$Latest"
  }
  min_size             = 1
  max_size             = 2
  desired_capacity     = 1

  tag {
    key                 = "Name"
    value               = "App Server"
    propagate_at_launch = true
  }
}

# ELB (Elastic Load Balancer) 생성
resource "aws_elb" "web" {
  name            = "web-load-balancer"
  security_groups = [aws_security_group.elb_sg.id]

  listener {
    instance_port     = 80
    instance_protocol = "HTTP"
    lb_port           = 80
    lb_protocol       = "HTTP"
  }

  health_check {
    target              = "HTTP:80/"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  # public 서브넷 ID 사용
  subnets = aws_subnet.public[*].id
}

# Auto Scaling 그룹과 ELB 연결
resource "aws_autoscaling_attachment" "asg_attachment" {
  autoscaling_group_name = aws_autoscaling_group.app.name
  elb                    = aws_elb.web.id
}

# 프라이빗 서브넷에 DB 인스턴스 생성
resource "aws_instance" "db" {
  count         = 2
  ami           = "ami-09da212cf18033880" # us-east-2 리전의 실제 AMI ID (DB용으로 적합한 AMI로 교체)
  instance_type = "t2.micro"
  subnet_id     = aws_subnet.private[count.index].id
  key_name      = "nm-pr-key" # 실제 키 쌍 이름

  tags = {
    Name = "DB Instance ${count.index + 1}"
  }
}

# S3 버킷 생성
resource "aws_s3_bucket" "content" {
  bucket = "mji-whi-s3" # 고유한 이름으로 변경
}

# CloudFront 배포 생성
resource "aws_cloudfront_distribution" "cdn" {
  origin {
    domain_name = aws_s3_bucket.content.bucket_regional_domain_name
    origin_id   = "test-tf-s3"
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "test-tf-s3"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# 보안 그룹 생성
resource "aws_security_group" "elb_sg" {
  name        = "elb_sg"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 출력
output "elb_dns_name" {
  value = aws_elb.web.dns_name
}
