---
id: OPT-34
title: Multi-tenant migration plan
status: Backlog
priority: None
created: 2026-02-05
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-34/multi-tenant-migration-plan
---

# OPT-34: Multi-tenant migration plan

# Multi-Tenancy Migration Plan: Container-per-User Architecture

## Summary

Migrate OptionLedger from a local single-user application to AWS with multi-tenant support using **container-per-user isolation**. Each user gets their own Docker container with isolated SQLite database, managed by AWS Fargate/App Runner.

## Why Container-per-User (Not Shared Database)

Given the requirements (1-50 users, important data isolation, minimize ops, single pricing tier):

| Factor | Container-per-User | Shared Database |
| -- | -- | -- |
| Code changes | Minimal | Significant (add tenant_id everywhere) |
| Data isolation | Physical separation | Logical (query-based) |
| Database | Keep SQLite | Must migrate to PostgreSQL |
| Ops complexity | Low with managed services | Low |
| Cost at 50 users | \~$100-200/mo | \~$80-150/mo |
| Security risk | Low | Higher (query filter bugs) |

**Winner**: Container-per-User - simpler migration, stronger isolation, minimal code changes

---

## Architecture Overview

```
Internet → CloudFront → ALB → ECS Fargate (1 container per user)
                ↓                    ↓
            Cognito             EFS (SQLite per user)
```

### AWS Services Used

| Service | Purpose | Why |
| -- | -- | -- |
| **ECS Fargate** | Container orchestration | Serverless containers, scales to zero if needed |
| **EFS** | Persistent storage | SQLite databases persist across container restarts |
| **ALB** | Load balancing & routing | Route users to their containers |
| **Cognito** | User authentication | Managed auth, JWT tokens |
| **CloudFront** | CDN & HTTPS | Cache static assets, SSL termination |
| **ECR** | Container registry | Store Docker images |
| **Secrets Manager** | API keys | Store any shared secrets |

---

## Implementation Phases

### Phase 1: Containerize the Application

**Goal**: Package current app as Docker container

**Changes Required**:

1. **Create Dockerfile** (`Dockerfile`)

   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   ENV PORT=8000
   ENV DATA_DIR=/data
   EXPOSE 8000
   CMD ["python", "app.py"]
   ```
2. **Modify **[**app.py**](<http://app.py>)** for container environment**:
   * Read `DATA_DIR` from environment (default: `/data`)
   * SQLite database path: `{DATA_DIR}/trade_journal.db`
   * Add health check endpoint: `GET /health`
   * Support `PORT` environment variable
3. **Add docker-compose.yml for local testing**:

   ```yaml
   version: '3.8'
   services:
     optionedge:
       build: .
       ports:
         - "8000:8000"
       volumes:
         - ./data:/data
       environment:
         - DATA_DIR=/data
   ```

**Files to Modify**:

* `app.py` - Environment variable support, health endpoint
* `src/database/db_manager.py` - Configurable database path

**New Files**:

* `Dockerfile`
* `docker-compose.yml`
* `.dockerignore`

---

### Phase 2: Add AWS Cognito Authentication

**Goal**: Replace session-based Tastytrade auth with Cognito user auth

**Current Auth Flow**:

```
User → /login (Tastytrade creds) → Session cookie → Protected endpoints
```

**New Auth Flow**:

```
User → Cognito login → JWT token → /api/link-tastytrade → Protected endpoints
```

**Changes Required**:

1. **Add Cognito JWT validation middleware**:
   * Validate JWT on all protected endpoints
   * Extract user_id from JWT claims
2. **Separate user auth from Tastytrade auth**:
   * Users log in to OptionEdge via Cognito
   * Users link Tastytrade account after login
   * Store encrypted Tastytrade refresh token in user's database
3. **New endpoints**:
   * `POST /api/link-tastytrade` - Link Tastytrade account
   * `DELETE /api/link-tastytrade` - Unlink account
   * `GET /api/account-status` - Check if Tastytrade linked

**Files to Modify**:

* `app.py` - Add Cognito middleware, new endpoints
* `static/login.html` - Replace with Cognito hosted UI redirect
* `src/api/tastytrade_client.py` - Support stored refresh tokens

**New Files**:

* `src/auth/cognito.py` - Cognito JWT validation
* `src/auth/tastytrade_link.py` - Tastytrade account linking

---

### Phase 3: AWS Infrastructure Setup

**Goal**: Deploy container infrastructure with Terraform/CDK

**Resources to Create**:

1. **Networking**:
   * VPC with public/private subnets
   * Security groups
2. **Container Infrastructure**:
   * ECS Cluster
   * Task definition (container spec)
   * ECS Service with auto-scaling
   * ALB with target group
3. **Storage**:
   * EFS file system
   * Access points (one per user or shared with subdirectories)
4. **Authentication**:
   * Cognito User Pool
   * App client
   * Domain for hosted UI
5. **Supporting**:
   * ECR repository
   * CloudWatch log groups
   * IAM roles

**New Files** (Infrastructure as Code):

* `infrastructure/` directory with Terraform or CDK

---

### Phase 4: User Provisioning & Routing

**Goal**: Automatically provision container when user signs up

**Provisioning Flow**:

```
1. User signs up in Cognito
2. Cognito triggers Lambda (post-confirmation)
3. Lambda creates:
   - EFS access point for user
   - ECS task definition with user's mount
   - Registers user in routing table
4. ALB routes user to their container
```

**Routing Strategy**:

Option A: **User Subdomain** (Recommended for <100 users)

```
user123.optionedge.com → ALB → User 123's container
```

Option B: **Header-based routing**

```
optionedge.com + X-User-Id header → ALB rule → Correct container
```

Option C: **Path-based with proxy**

```
optionedge.com → API Gateway/Lambda → Proxy to user container
```

**Recommendation**: Start with Option B (header-based) - simpler, no DNS management

---

### Phase 5: CI/CD Pipeline

**Goal**: Automated deployments

**Pipeline Steps**:

1. Push to main → GitHub Actions triggered
2. Build Docker image
3. Push to ECR
4. Update ECS task definition
5. Rolling update across all user containers

**New Files**:

* `.github/workflows/deploy.yml`

---

## Cost Estimate (50 Users)

| Service | Monthly Cost |
| -- | -- |
| ECS Fargate (50 containers, 0.25 vCPU, 512MB each) | \~$75 |
| EFS | \~$15 |
| ALB | \~$20 |
| Cognito | Free tier (50k MAU free) |
| CloudFront | \~$10 |
| ECR | \~$5 |
| **Total** | **\~$125/month** |

*Note: Costs can be reduced with:*

* *Spot Fargate (60% savings)*
* *Scale-to-zero when user inactive*
* *Reserved capacity for predictable workloads*

---

## Migration Path

### Stage 1: Local Docker (Week 1)

* Containerize app
* Test locally with docker-compose
* No AWS yet

### Stage 2: Single-Container AWS (Week 2)

* Deploy one container to Fargate
* Set up Cognito
* Single user testing

### Stage 3: Multi-User (Week 3-4)

* Implement user provisioning
* EFS per-user mounts
* ALB routing
* Test with 3-5 users

### Stage 4: Production (Week 5+)

* CI/CD pipeline
* Monitoring & alerting
* Documentation
* Beta launch

---

## Security Considerations

1. **Tastytrade Credentials**:
   * Never store raw credentials
   * Use Tastytrade refresh tokens (encrypted at rest)
   * Tokens stored in user's isolated database
2. **Container Isolation**:
   * Each container in separate security group
   * No inter-container communication
   * EFS access points enforce user isolation
3. **Network Security**:
   * HTTPS only (CloudFront SSL)
   * Private subnets for containers
   * VPC endpoints for AWS services
4. **Authentication**:
   * Cognito handles password policies, MFA
   * Short-lived JWT tokens
   * Refresh token rotation

---

## Files to Create/Modify Summary

### New Files

* `Dockerfile`
* `docker-compose.yml`
* `.dockerignore`
* `src/auth/cognito.py`
* `src/auth/tastytrade_link.py`
* `infrastructure/` (Terraform/CDK)
* `.github/workflows/deploy.yml`

### Modified Files

* `app.py` - Container env vars, health endpoint, Cognito auth
* `src/database/db_manager.py` - Configurable DB path
* `static/login.html` - Cognito redirect
* `src/api/tastytrade_client.py` - Refresh token support
* `requirements.txt` - Add cognito/jwt libraries

---

## Verification Plan

1. **Local Docker Testing**:
   * Build and run container locally
   * Verify SQLite persistence across restarts
   * Test all existing functionality
2. **AWS Single-User**:
   * Deploy to Fargate
   * Test Cognito login flow
   * Verify EFS persistence
   * Test Tastytrade sync
3. **Multi-User Testing**:
   * Create 3 test users
   * Verify complete isolation (user A can't see user B's data)
   * Test concurrent usage
   * Test container restart preserves data
4. **Load Testing**:
   * Simulate 50 concurrent users
   * Verify ALB routing
   * Check resource utilization

---

## Alternative Considered: Shared Database

If you later grow to 500+ users and want to reduce costs, you can migrate to a shared PostgreSQL database with tenant_id. The container-per-user approach doesn't lock you out of this path - the data model migration would be similar either way.

For now, container-per-user gives you:

* Faster time to market (minimal code changes)
* Stronger isolation story for financial data
* Simpler debugging (one user per container)
* Clear upgrade path if needed
